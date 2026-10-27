import {
  Bot,
  Camera,
  CheckCircle2,
  ChevronDown,
  GitFork,
  Network,
  Play,
  Route,
  Search,
  Workflow,
  Wrench,
} from 'lucide-react';
import { useState } from 'react';
import {
  cleanDecision,
  formatTransitionType,
  getStepTitle,
} from '../routingTrace';
import type { RoutingStep } from '../types';

type Props = {
  messageId: string;
  operationId: string;
  routing: RoutingStep[] | null;
};

function getStepIcon(step: RoutingStep) {
  const toNode = (step.to_node || '').toUpperCase();
  const fromNode = (step.from_node || '').toUpperCase();
  const toSub = (step.to_subagent || '').toLowerCase();
  const fromSub = (step.from_subagent || '').toLowerCase();
  const toTool = (step.to_tool || '').toLowerCase();
  const type = (step.routing_type || '').toLowerCase();

  if (toNode === 'END') return CheckCircle2;
  if (fromNode === 'START') return Play;

  if (toSub.includes('knowledge') || fromSub.includes('knowledge') || toTool.includes('graph')) {
    return Network;
  }
  if (toSub.includes('text') || toSub.includes('entity') || fromSub.includes('text') || toTool.includes('name')) {
    return Search;
  }
  if (toSub.includes('image') || fromSub.includes('image') || toTool.includes('image')) {
    return Camera;
  }
  if (type === 'subagent_delegation') return GitFork;
  if (type === 'tool_selection') return Wrench;
  if (type === 'subagent_handoff' || toNode.includes('orchestrator') || fromNode.includes('orchestrator')) {
    return Bot;
  }

  return Workflow;
}

export function AgentRoutingTrace({ messageId, operationId, routing }: Props) {
  const [isExpanded, setIsExpanded] = useState(false);
  const hasSteps = Array.isArray(routing) && routing.length > 0;
  const flowId = `routing-flow-${messageId}`;

  return (
    <div className="agent-routing-container" data-operation-id={operationId}>
      <button
        type="button"
        className={`agent-routing-toggle ${isExpanded ? 'expanded' : ''}`}
        onClick={() => setIsExpanded(prev => !prev)}
        aria-expanded={isExpanded}
        aria-controls={flowId}
      >
        <span className="agent-routing-title">
          <Route size={14} className="agent-routing-icon-lead" aria-hidden="true" />
          <span>How this answer was generated</span>
        </span>
        <span className="agent-routing-action">
          <span>{isExpanded ? 'Hide agent flow' : 'View agent flow'}</span>
          <ChevronDown
            size={14}
            className={`agent-routing-chevron ${isExpanded ? 'rotated' : ''}`}
            aria-hidden="true"
          />
        </span>
      </button>

      {isExpanded && (
        <div
          id={flowId}
          className="agent-routing-flow"
          role="region"
          aria-label="Agent routing execution flow"
        >
          {!hasSteps ? (
            <p className="agent-routing-empty">
              Routing information is not available for this response.
            </p>
          ) : (
            <div className="routing-flow-timeline">
              {routing.map((step, index) => {
                const isLast = index === routing.length - 1;
                const StepIcon = getStepIcon(step);
                const { combined } = getStepTitle(step);
                const transitionType = formatTransitionType(step.routing_type);
                const decisionText = cleanDecision(step.decision);
                const stepNum = typeof step.step === 'number' ? step.step : index + 1;

                return (
                  <div className="routing-flow-step" key={step.step ?? index}>
                    <div className="routing-flow-rail">
                      <div className="routing-flow-badge" title={combined}>
                        <StepIcon size={13} strokeWidth={2} aria-hidden="true" />
                      </div>
                      {!isLast && <div className="routing-flow-line" aria-hidden="true" />}
                    </div>
                    <div className="routing-flow-content">
                      <div className="routing-flow-header">
                        <span className="routing-step-index">Step {stepNum}</span>
                        <strong className="routing-step-title">{combined}</strong>
                        <span className="routing-step-type">{transitionType}</span>
                      </div>
                      {decisionText && (
                        <p className="routing-step-decision">{decisionText}</p>
                      )}
                      {step.condition && (
                        <div className="routing-step-condition">
                          <span className="condition-label">Condition:</span>
                          <code>{String(step.condition)}</code>
                        </div>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
