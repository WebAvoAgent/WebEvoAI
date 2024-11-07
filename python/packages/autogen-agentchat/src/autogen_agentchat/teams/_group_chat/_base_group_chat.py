import asyncio
import logging
import uuid
from abc import ABC, abstractmethod
from typing import AsyncGenerator, Callable, List

from autogen_core.application import SingleThreadedAgentRuntime
from autogen_core.base import (
    AgentId,
    AgentInstantiationContext,
    AgentRuntime,
    AgentType,
    CancellationToken,
    MessageContext,
    TopicId,
)
from autogen_core.components import ClosureAgent, TypeSubscription

from ... import EVENT_LOGGER_NAME
from ...base import ChatAgent, TaskResult, Team, TerminationCondition
from ...messages import AgentMessage, TextMessage
from ._base_group_chat_manager import BaseGroupChatManager
from ._chat_agent_container import ChatAgentContainer
from ._events import GroupChatMessage, GroupChatStart, GroupChatTermination, GroupChatReset

event_logger = logging.getLogger(EVENT_LOGGER_NAME)


class BaseGroupChat(Team, ABC):
    """The base class for group chat teams.

    To implement a group chat team, first create a subclass of :class:`BaseGroupChatManager` and then
    create a subclass of :class:`BaseGroupChat` that uses the group chat manager.
    """

    def __init__(
        self,
        participants: List[ChatAgent],
        group_chat_manager_class: type[BaseGroupChatManager],
        termination_condition: TerminationCondition | None = None,
    ):
        if len(participants) == 0:
            raise ValueError("At least one participant is required.")
        if len(participants) != len(set(participant.name for participant in participants)):
            raise ValueError("The participant names must be unique.")
        self._participants = participants
        self._team_id = str(uuid.uuid4())
        self._base_group_chat_manager_class = group_chat_manager_class
        self._termination_condition = termination_condition
        self._message_thread: List[AgentMessage] = []
        # Constants for the group chat.
        self._group_topic_type = "group_topic"
        self._output_topic_type = "output_topic"
        self._group_chat_manager_topic_type = "group_chat_manager"
        self._participant_topic_types: List[str] = [participant.name for participant in participants]
        self._participant_descriptions: List[str] = [participant.description for participant in participants]
        self._collector_agent_type = "collect_output_messages"
        # Constants for the closure agent to collect the output messages.
        self._stop_reason: str | None = None
        self._output_message_queue: asyncio.Queue[AgentMessage | None] = asyncio.Queue()

        # Create a runtime for the team.
        # TODO: The runtime should be created by a managed context.
        self._runtime = SingleThreadedAgentRuntime()

        self._initialized = False

    @abstractmethod
    def _create_group_chat_manager_factory(
        self,
        group_topic_type: str,
        output_topic_type: str,
        participant_topic_types: List[str],
        participant_descriptions: List[str],
        message_thread: List[AgentMessage],
        termination_condition: TerminationCondition | None,
    ) -> Callable[[], BaseGroupChatManager]: ...

    def _create_participant_factory(
        self,
        parent_topic_type: str,
        output_topic_type: str,
        agent: ChatAgent,
    ) -> Callable[[], ChatAgentContainer]:
        def _factory() -> ChatAgentContainer:
            id = AgentInstantiationContext.current_agent_id()
            assert id == AgentId(type=agent.name, key=self._team_id)
            container = ChatAgentContainer(parent_topic_type, output_topic_type, agent)
            assert container.id == id
            return container

        return _factory
    
    async def _init(self, runtime: AgentRuntime) -> None:
        # Constants for the group chat manager.
        group_chat_manager_agent_type = AgentType(self._group_chat_manager_topic_type)

        # Register participants.
        for participant, participant_topic_type in zip(self._participants, self._participant_topic_types):
            # Use the participant topic type as the agent type.
            agent_type = participant_topic_type
            # Register the participant factory.
            await ChatAgentContainer.register(
                runtime,
                type=agent_type,
                factory=self._create_participant_factory(self._group_topic_type, self._output_topic_type, participant),
            )
            # Add subscriptions for the participant.
            await runtime.add_subscription(TypeSubscription(topic_type=participant_topic_type, agent_type=agent_type))
            await runtime.add_subscription(TypeSubscription(topic_type=self._group_topic_type, agent_type=agent_type))

        # Register the group chat manager.
        await self._base_group_chat_manager_class.register(
            runtime,
            type=group_chat_manager_agent_type.type,
            factory=self._create_group_chat_manager_factory(
                group_topic_type=self._group_topic_type,
                output_topic_type=self._output_topic_type,
                participant_topic_types=self._participant_topic_types,
                participant_descriptions=self._participant_descriptions,
                message_thread=self._message_thread,
                termination_condition=self._termination_condition,
            ),
        )
        # Add subscriptions for the group chat manager.
        await runtime.add_subscription(
            TypeSubscription(topic_type=self._group_chat_manager_topic_type, agent_type=group_chat_manager_agent_type.type)
        )
        await runtime.add_subscription(
            TypeSubscription(topic_type=self._group_topic_type, agent_type=group_chat_manager_agent_type.type)
        )

        async def collect_output_messages(
            _runtime: AgentRuntime,
            id: AgentId,
            message: GroupChatStart | GroupChatMessage | GroupChatTermination,
            ctx: MessageContext,
        ) -> None:
            event_logger.info(message.message)
            if isinstance(message, GroupChatTermination):
                self._stop_reason = message.message.content
                return
            await self._output_message_queue.put(message.message)

        await ClosureAgent.register(
            runtime,
            type=self._collector_agent_type,
            closure=collect_output_messages,
            subscriptions=lambda: [
                TypeSubscription(topic_type=self._output_topic_type, agent_type=self._collector_agent_type),
            ],
        )

    async def run(
        self,
        *,
        task: str | None = None,
        cancellation_token: CancellationToken | None = None,
    ) -> TaskResult:
        """Run the team and return the result. The base implementation uses
        :meth:`run_stream` to run the team and then returns the final result."""
        async for message in self.run_stream(
            task=task,
            cancellation_token=cancellation_token,
        ):
            if isinstance(message, TaskResult):
                return message
        raise AssertionError("The stream should have returned the final result.")

    async def run_stream(
        self,
        *,
        task: str | None = None,
        cancellation_token: CancellationToken | None = None,
    ) -> AsyncGenerator[AgentMessage | TaskResult, None]:
        """Run the team and produces a stream of messages and the final result
        of the type :class:`TaskResult` as the last item in the stream."""

        # Start the runtime.
        # TODO: The runtime should be started by a managed context.
        self._runtime.start()

        if not self._initialized:
            await self._init(self._runtime)
            self._initialized = True

        # Run the team by publishing the start message.
        if task is None:
            first_chat_message = None
        else:
            first_chat_message = TextMessage(content=task, source="user")
        await self._runtime.publish_message(
            GroupChatStart(message=first_chat_message),
            topic_id=TopicId(type=self._group_topic_type, source=self._team_id),
        )

        # Start a coroutine to stop the runtime and signal the output message queue is complete.
        async def stop_runtime() -> None:
            await self._runtime.stop_when_idle()
            await self._output_message_queue.put(None)

        shutdown_task = asyncio.create_task(stop_runtime())

        # Collect the output messages in order.
        output_messages: List[AgentMessage] = []
        # Yield the messsages until the queue is empty.
        while True:
            message = await self._output_message_queue.get()
            if message is None:
                break
            yield message
            output_messages.append(message)

        # Wait for the shutdown task to finish.
        await shutdown_task

        # Yield the final result.
        yield TaskResult(messages=output_messages, stop_reason=self._stop_reason)


    async def reset(self) -> None:
        """Reset the group chat and its participants."""

        if not self._initialized:
            raise ValueError("The group chat has not been initialized. It must be run before it can be reset.")
        
        if self._is_running:
            raise ValueError("The group chat is currently running. It must be stopped before it can be reset.")
        
        # Send a reset message to the group chat.
        await self._runtime.publish_message(
            GroupChatReset(),
            topic_id=TopicId(type=self._group_topic_type, source=self._team_id),
        )