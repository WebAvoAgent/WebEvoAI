// Copyright (c) Microsoft Corporation. All rights reserved.
// IAgentState.cs

namespace Microsoft.AutoGen.Abstractions;

public interface IAgentState : IGrainWithStringKey
{
    ValueTask<AgentState> ReadStateAsync();
    ValueTask<string> WriteStateAsync(AgentState state, string eTag);
}
