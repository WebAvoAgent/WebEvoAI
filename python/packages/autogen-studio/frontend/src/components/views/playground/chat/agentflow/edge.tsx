import React from "react";
import { Tabs, Tooltip } from "antd";
import { AgentMessageConfig } from "../../../../types/datamodel";
import {
  EdgeLabelRenderer,
  type EdgeProps,
  getSmoothStepPath, // Add this import
} from "@xyflow/react";
import { RenderMessage } from "../rendermessage";

interface EdgeTooltipContentProps {
  messages: AgentMessageConfig[];
}

interface CustomEdgeData {
  label?: string;
  messages: AgentMessageConfig[];
}

export const EdgeTooltipContent: React.FC<EdgeTooltipContentProps> = ({
  messages,
}) => {
  return (
    <div className="edge-tooltip">
      <Tabs
        defaultActiveKey="0"
        size="small"
        style={{
          maxWidth: "400px",
          maxHeight: "300px",
        }}
        items={messages.map((msg, index) => ({
          key: String(index),
          label: `Message ${index + 1}`,
          children: (
            <div className="p-2 overflow-auto max-h-[250px] scroll">
              <pre className="whitespace-pre-wrap text-white  text-xs">
                <RenderMessage message={msg} />
              </pre>
              <div className="text-xs text-primary mt-2">
                {msg.models_usage &&
                  `Tokens: ${
                    msg.models_usage.prompt_tokens +
                    msg.models_usage.completion_tokens
                  }`}
              </div>
            </div>
          ),
        }))}
      />
    </div>
  );
};

interface CustomEdgeProps extends Omit<EdgeProps, "data"> {
  data: CustomEdgeData;
}

export const CustomEdge: React.FC<CustomEdgeProps> = ({
  id,
  sourceX,
  sourceY,
  targetX,
  targetY,
  source,
  target,
  data,
  style = {},
  markerEnd,
  sourcePosition,
  targetPosition,
}) => {
  const isSelfLoop = source === target;

  let edgePath = "";
  let labelX = 0;
  let labelY = 0;

  if (isSelfLoop) {
    const rightOffset = 120; // How far right the path extends
    const verticalOffset = sourceY - targetY; // Base vertical distance between handles
    const verticalPadding = 6; // Extra padding above/below handles
    const radius = 8; // Radius for rounded corners

    // Start and end slightly beyond the handles using verticalPadding
    edgePath = `
      M ${sourceX} ${targetY - verticalPadding}  
      L ${sourceX + rightOffset - radius} ${targetY - verticalPadding}
      Q ${sourceX + rightOffset} ${targetY - verticalPadding} ${
      sourceX + rightOffset
    } ${targetY - verticalPadding + radius}
      L ${sourceX + rightOffset} ${sourceY + verticalPadding - radius}
      Q ${sourceX + rightOffset} ${sourceY + verticalPadding} ${
      sourceX + rightOffset - radius
    } ${sourceY + verticalPadding}
      L ${sourceX} ${sourceY + verticalPadding}
    `;

    // Adjust label position to account for padding
    labelX = sourceX + rightOffset + 10;
    labelY = targetY + verticalOffset / 2;
  } else {
    [edgePath, labelX, labelY] = getSmoothStepPath({
      sourceX,
      sourceY,
      targetX,
      targetY,
    });
  }

  return (
    <>
      <path
        id={id}
        className="react-flow__edge-path"
        d={edgePath}
        style={{
          ...style,
          strokeWidth: isSelfLoop
            ? Math.max((style.strokeWidth as number) || 1, 2)
            : style.strokeWidth,
        }}
        markerEnd={markerEnd}
      />
      {data?.label && (
        <EdgeLabelRenderer>
          <div
            style={{
              position: "absolute",
              transform: `translate(-50%, -50%) translate(${labelX}px,${labelY}px)`,
              pointerEvents: "all",
            }}
          >
            <Tooltip
              title={
                data.messages && data.messages.length > 0 ? (
                  <EdgeTooltipContent messages={data.messages} />
                ) : (
                  data?.label
                )
              }
              overlayStyle={{ maxWidth: "none" }}
            >
              <div className="px-2 py-1 rounded bg-secondary bg-opacity-50 text-primary text-sm">
                {data.label}
              </div>
            </Tooltip>
          </div>
        </EdgeLabelRenderer>
      )}
    </>
  );
};
