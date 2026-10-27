import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import {
  extractRouting,
  sanitizeRouting,
  formatNodeLabel,
  formatTransitionType,
  getStepTitle,
  cleanDecision,
} from './routingTrace.ts';

test('extractRouting parses canonical traces.routing structure', () => {
  const message = {
    message_id: 'msg-1',
    operation_id: 'op-1',
    role: 'assistant',
    content: 'Answer content',
    status: 'complete',
    data: {
      traces: {
        routing: [
          {
            step: 1,
            routing_type: 'graph_node_transition',
            from_node: 'START',
            to_node: 'deep_orchestrator',
            decision: "Route question to deep_orchestrator with plant scope locked to 'Ocimum sanctum'",
          },
          {
            step: 2,
            routing_type: 'subagent_delegation',
            from_agent: 'orchestrator',
            to_subagent: 'knowledge_graph',
            decision: 'Orchestrator delegates domain fact retrieval',
          },
        ],
      },
    },
    created_at: '2026-10-27T10:00:00Z',
  };

  const steps = extractRouting(message);
  assert.ok(steps);
  assert.equal(steps.length, 2);
  assert.equal(steps[0].step, 1);
  assert.equal(steps[0].routing_type, 'graph_node_transition');
  assert.equal(steps[0].from_node, 'START');
  assert.equal(steps[0].to_node, 'deep_orchestrator');
  assert.equal(steps[1].to_subagent, 'knowledge_graph');
});

test('extractRouting parses direct data.routing and nested result.traces.routing', () => {
  const directMessage = {
    message_id: 'msg-2',
    operation_id: 'op-2',
    role: 'assistant',
    content: 'Direct answer',
    status: 'complete',
    data: {
      routing: [
        { step: 1, routing_type: 'graph_node_transition', to_node: 'deep_orchestrator' },
      ],
    },
    created_at: '2026-10-27T10:00:00Z',
  };
  const directSteps = extractRouting(directMessage);
  assert.ok(directSteps);
  assert.equal(directSteps.length, 1);
  assert.equal(directSteps[0].to_node, 'deep_orchestrator');

  const nestedMessage = {
    message_id: 'msg-3',
    operation_id: 'op-3',
    role: 'assistant',
    content: 'Nested answer',
    status: 'complete',
    data: {
      result: {
        traces: {
          routing: [
            { step: 1, routing_type: 'graph_conditional_edge', to_node: 'END' },
          ],
        },
      },
    },
    created_at: '2026-10-27T10:00:00Z',
  };
  const nestedSteps = extractRouting(nestedMessage);
  assert.ok(nestedSteps);
  assert.equal(nestedSteps.length, 1);
  assert.equal(nestedSteps[0].to_node, 'END');
});

test('extractRouting safely handles missing, null, or malformed routing data', () => {
  assert.equal(extractRouting(null), null);
  assert.equal(extractRouting(undefined), null);
  assert.equal(extractRouting({}), null);
  assert.equal(extractRouting({ role: 'assistant', data: {} }), null);
  assert.equal(extractRouting({ role: 'assistant', data: { traces: {} } }), null);
  assert.equal(extractRouting({ role: 'assistant', data: { traces: { routing: 'not-an-array' } } }), null);
  assert.equal(extractRouting({ role: 'assistant', data: { routing: null } }), null);

  // If empty array exists, it returns empty array
  const emptyMessage = { role: 'assistant', data: { traces: { routing: [] } } };
  assert.deepEqual(extractRouting(emptyMessage), []);
});

test('sanitizeRouting sorts steps chronologically and discards non-routing payload pollution', () => {
  const raw = [
    {
      step: 2,
      routing_type: 'subagent_handoff',
      from_subagent: 'knowledge_graph',
      to_agent: 'orchestrator',
      // Polluting fields that should NOT be in routing trace
      raw_tool_result: { secret_sql: 'SELECT * FROM users' },
      agent_reasoning: 'Private model thoughts',
    },
    null,
    'corrupted string',
    {
      step: 1,
      routing_type: 'graph_node_transition',
      from_node: 'START',
      to_node: 'deep_orchestrator',
    },
  ];

  const sanitized = sanitizeRouting(raw);
  assert.equal(sanitized.length, 2);
  // Order is restored by step number
  assert.equal(sanitized[0].step, 1);
  assert.equal(sanitized[0].from_node, 'START');
  assert.equal(sanitized[1].step, 2);
  assert.equal(sanitized[1].from_subagent, 'knowledge_graph');
  // Polluting fields are stripped
  assert.equal('raw_tool_result' in sanitized[1], false);
  assert.equal('agent_reasoning' in sanitized[1], false);
});

test('formatNodeLabel produces friendly labels for all known agents and nodes', () => {
  assert.equal(formatNodeLabel('START'), 'Start');
  assert.equal(formatNodeLabel('END'), 'Completed');
  assert.equal(formatNodeLabel('deep_orchestrator'), 'Orchestrator');
  assert.equal(formatNodeLabel('orchestrator'), 'Orchestrator');
  assert.equal(formatNodeLabel('knowledge_graph'), 'Knowledge Graph Agent');
  assert.equal(formatNodeLabel('text_entity'), 'Plant Name Resolution');
  assert.equal(formatNodeLabel('image_understanding'), 'Image Understanding');
  assert.equal(formatNodeLabel('specialist'), 'Specialist Agent');
  assert.equal(formatNodeLabel('retrieve_plant_graph'), 'Plant Graph Retrieval');
  assert.equal(formatNodeLabel('resolve_plant_names'), 'Plant Name Resolution');
  assert.equal(formatNodeLabel('inspect_uploaded_image'), 'Image Classifier');
  assert.equal(formatNodeLabel('custom_agent'), 'Custom Agent');
  assert.equal(formatNodeLabel(''), 'Unknown');
  assert.equal(formatNodeLabel(null), 'Unknown');
});

test('formatTransitionType translates technical types into clear human phrases', () => {
  assert.equal(formatTransitionType('subagent_delegation'), 'Delegated the request');
  assert.equal(formatTransitionType('subagent_handoff'), 'Returned control to the orchestrator');
  assert.equal(formatTransitionType('graph_node_transition'), 'Moved to the next stage');
  assert.equal(formatTransitionType('graph_conditional_edge'), 'Selected the next step');
  assert.equal(formatTransitionType('tool_selection'), 'Selected retrieval tool');
  assert.equal(formatTransitionType('unknown_transition'), 'unknown transition');
  assert.equal(formatTransitionType(null), 'Transitioned');
});

test('getStepTitle creates clear node-to-node representations', () => {
  const delegation = {
    step: 2,
    routing_type: 'subagent_delegation',
    from_agent: 'orchestrator',
    to_subagent: 'specialist',
    details: { description: 'subagent_type: knowledge_graph' },
  };
  const title1 = getStepTitle(delegation);
  assert.equal(title1.combined, 'Orchestrator → Knowledge Graph Agent');

  const toolStep = {
    step: 3,
    routing_type: 'tool_selection',
    from_subagent: 'knowledge_graph',
    to_tool: 'retrieve_plant_graph',
  };
  const title2 = getStepTitle(toolStep);
  assert.equal(title2.combined, 'Knowledge Graph Agent → Plant Graph Retrieval');

  const handoff = {
    step: 4,
    routing_type: 'subagent_handoff',
    from_subagent: 'knowledge_graph',
    to_agent: 'orchestrator',
  };
  const title3 = getStepTitle(handoff);
  assert.equal(title3.combined, 'Knowledge Graph Agent → Orchestrator');

  const edge = {
    step: 5,
    routing_type: 'graph_conditional_edge',
    from_node: 'deep_orchestrator',
    to_node: 'END',
  };
  const title4 = getStepTitle(edge);
  assert.equal(title4.combined, 'Orchestrator → Completed');
});

test('cleanDecision sanitizes decision prose and suppresses secrets', () => {
  assert.equal(cleanDecision('"Route question to deep_orchestrator"'), 'Route question to deep_orchestrator');
  assert.equal(cleanDecision("'Turn objectives satisfied'"), 'Turn objectives satisfied');
  assert.equal(cleanDecision('Contains secret_token=12345'), 'Routing transition recorded.');
  assert.equal(cleanDecision(''), '');
  assert.equal(cleanDecision(null), '');
});

test('verification against actual recorded evaluation trace from data/evaluation_sample.jsonl', () => {
  const samplePath = path.resolve('..', 'data', 'evaluation_sample.jsonl');
  if (!fs.existsSync(samplePath)) {
    return; // Skip if run from different root
  }
  const firstLine = fs.readFileSync(samplePath, 'utf-8').split('\n')[0];
  const parsed = JSON.parse(firstLine);
  assert.ok(parsed.traces?.routing, 'evaluation sample must contain routing trace');

  const mockMessage = {
    message_id: 'sample-eval-msg',
    operation_id: 'sample-eval-op',
    role: 'assistant',
    content: parsed.response,
    status: 'complete',
    data: { traces: parsed.traces },
    created_at: '2026-10-26T14:55:50Z',
  };

  const routing = extractRouting(mockMessage);
  assert.ok(routing);
  assert.equal(routing.length, 5);

  // Step 1: START -> deep_orchestrator
  assert.equal(routing[0].routing_type, 'graph_node_transition');
  assert.equal(formatTransitionType(routing[0].routing_type), 'Moved to the next stage');
  assert.equal(getStepTitle(routing[0]).combined, 'Start → Orchestrator');

  // Step 2: Orchestrator -> Specialist (knowledge_graph)
  assert.equal(routing[1].routing_type, 'subagent_delegation');
  assert.equal(formatTransitionType(routing[1].routing_type), 'Delegated the request');
  assert.equal(getStepTitle(routing[1]).combined, 'Orchestrator → Knowledge Graph Agent');

  // Step 3: knowledge_graph -> retrieve_plant_graph
  assert.equal(routing[2].routing_type, 'tool_selection');
  assert.equal(formatTransitionType(routing[2].routing_type), 'Selected retrieval tool');
  assert.equal(getStepTitle(routing[2]).combined, 'Knowledge Graph Agent → Plant Graph Retrieval');

  // Step 4: subagent_handoff
  assert.equal(routing[3].routing_type, 'subagent_handoff');
  assert.equal(formatTransitionType(routing[3].routing_type), 'Returned control to the orchestrator');
  assert.equal(getStepTitle(routing[3]).combined, 'Specialist Agent → Orchestrator');

  // Step 5: conditional edge to END
  assert.equal(routing[4].routing_type, 'graph_conditional_edge');
  assert.equal(formatTransitionType(routing[4].routing_type), 'Selected the next step');
  assert.equal(getStepTitle(routing[4]).combined, 'Orchestrator → Completed');
  assert.equal(routing[4].condition, 'status == COMPLETE');
});

test('trace association: each message retains only its own distinct trace', () => {
  const msg1 = {
    message_id: 'msg-turn-1',
    operation_id: 'op-1',
    role: 'assistant',
    content: 'First answer',
    status: 'complete',
    data: {
      traces: {
        routing: [
          { step: 1, routing_type: 'graph_node_transition', from_node: 'START', to_node: 'deep_orchestrator' },
        ],
      },
    },
    created_at: '2026-10-27T10:00:00Z',
  };

  const msg2 = {
    message_id: 'msg-turn-2',
    operation_id: 'op-2',
    role: 'assistant',
    content: 'Second answer',
    status: 'complete',
    data: {
      traces: {
        routing: [
          { step: 1, routing_type: 'subagent_delegation', from_agent: 'orchestrator', to_subagent: 'text_entity' },
          { step: 2, routing_type: 'subagent_handoff', from_subagent: 'text_entity', to_agent: 'orchestrator' },
        ],
      },
    },
    created_at: '2026-10-27T10:05:00Z',
  };

  const msg3WithoutTrace = {
    message_id: 'msg-turn-3',
    operation_id: 'op-3',
    role: 'assistant',
    content: 'Third answer without trace',
    status: 'complete',
    data: {},
    created_at: '2026-10-27T10:10:00Z',
  };

  const trace1 = extractRouting(msg1);
  const trace2 = extractRouting(msg2);
  const trace3 = extractRouting(msg3WithoutTrace);

  assert.equal(trace1.length, 1);
  assert.equal(trace1[0].to_node, 'deep_orchestrator');

  assert.equal(trace2.length, 2);
  assert.equal(trace2[0].to_subagent, 'text_entity');
  assert.equal(trace2[1].from_subagent, 'text_entity');

  assert.equal(trace3, null);

  // Cross-verification: msg2 never leaks trace1, msg3 never inherits trace2
  assert.notDeepEqual(trace1, trace2);
  assert.notEqual(trace2, null);
});
