import type { Message, RoutingStep, RoutingType } from './types';

/**
 * Extracts and sanitizes the routing trace associated with a specific message.
 * Supports multiple standard serialization formats safely.
 */
export function extractRouting(message: Message | null | undefined): RoutingStep[] | null {
  if (!message || typeof message !== 'object') return null;
  const data = message.data;
  if (!data || typeof data !== 'object') {
    // Check direct message properties as fallback
    const direct = message as unknown as Record<string, unknown>;
    if (direct.traces && typeof direct.traces === 'object' && Array.isArray((direct.traces as Record<string, unknown>).routing)) {
      return sanitizeRouting((direct.traces as Record<string, unknown>).routing as unknown[]);
    }
    if (Array.isArray(direct.routing)) {
      return sanitizeRouting(direct.routing as unknown[]);
    }
    return null;
  }

  // 1. Canonical: message.data.traces.routing
  const traces = (data as Record<string, unknown>).traces;
  if (traces && typeof traces === 'object' && Array.isArray((traces as Record<string, unknown>).routing)) {
    return sanitizeRouting((traces as Record<string, unknown>).routing as unknown[]);
  }

  // 2. Direct: message.data.routing
  if (Array.isArray((data as Record<string, unknown>).routing)) {
    return sanitizeRouting((data as Record<string, unknown>).routing as unknown[]);
  }

  // 3. Nested in result: message.data.result.traces.routing or message.data.result.routing
  const result = (data as Record<string, unknown>).result;
  if (result && typeof result === 'object') {
    const resTraces = (result as Record<string, unknown>).traces;
    if (resTraces && typeof resTraces === 'object' && Array.isArray((resTraces as Record<string, unknown>).routing)) {
      return sanitizeRouting((resTraces as Record<string, unknown>).routing as unknown[]);
    }
    if (Array.isArray((result as Record<string, unknown>).routing)) {
      return sanitizeRouting((result as Record<string, unknown>).routing as unknown[]);
    }
  }

  return null;
}

/**
 * Sanitizes raw routing events: validates fields, preserves chronological order,
 * and strips any non-routing payloads (e.g. tool inputs/outputs, thoughts).
 */
export function sanitizeRouting(rawSteps: unknown[]): RoutingStep[] {
  if (!Array.isArray(rawSteps)) return [];

  const sanitized: RoutingStep[] = [];

  for (const item of rawSteps) {
    if (!item || typeof item !== 'object') continue;
    const obj = item as Record<string, unknown>;

    const stepNum = typeof obj.step === 'number' && Number.isFinite(obj.step)
      ? obj.step
      : typeof obj.step === 'string' && /^\d+$/.test(obj.step)
        ? parseInt(obj.step, 10)
        : undefined;

    const routingType: RoutingType | undefined = typeof obj.routing_type === 'string'
      ? obj.routing_type.trim()
      : undefined;

    const fromNode = typeof obj.from_node === 'string' ? obj.from_node.trim() : null;
    const toNode = typeof obj.to_node === 'string' ? obj.to_node.trim() : null;
    const fromAgent = typeof obj.from_agent === 'string' ? obj.from_agent.trim() : null;
    const toSubagent = typeof obj.to_subagent === 'string' ? obj.to_subagent.trim() : null;
    const fromSubagent = typeof obj.from_subagent === 'string' ? obj.from_subagent.trim() : null;
    const toAgent = typeof obj.to_agent === 'string' ? obj.to_agent.trim() : null;
    const toTool = typeof obj.to_tool === 'string' ? obj.to_tool.trim() : null;
    const toolInvoked = typeof obj.tool_invoked === 'string' ? obj.tool_invoked.trim() : null;
    const decision = typeof obj.decision === 'string' ? obj.decision.trim() : null;
    const condition = typeof obj.condition === 'string' ? obj.condition.trim() : null;
    const timestamp = typeof obj.timestamp === 'string' ? obj.timestamp.trim() : null;

    let details: Record<string, unknown> | null = null;
    if (obj.details && typeof obj.details === 'object' && !Array.isArray(obj.details)) {
      details = obj.details as Record<string, unknown>;
    }

    sanitized.push({
      step: stepNum,
      routing_type: routingType,
      from_node: fromNode,
      to_node: toNode,
      from_agent: fromAgent,
      to_subagent: toSubagent,
      from_subagent: fromSubagent,
      to_agent: toAgent,
      to_tool: toTool,
      tool_invoked: toolInvoked,
      decision,
      condition,
      timestamp,
      details,
    });
  }

  // Sort by step number if consistently present, preserving recorded order
  const hasStepNumbers = sanitized.length > 0 && sanitized.every(s => typeof s.step === 'number');
  if (hasStepNumbers) {
    sanitized.sort((a, b) => (a.step ?? 0) - (b.step ?? 0));
  }

  return sanitized;
}

/**
 * Maps internal node and agent keys to human-friendly display names.
 */
export function formatNodeLabel(raw: string | null | undefined): string {
  if (!raw) return 'Unknown';
  const clean = raw.trim();
  const lower = clean.toLowerCase();

  switch (lower) {
    case 'start':
      return 'Start';
    case 'end':
      return 'Completed';
    case 'deep_orchestrator':
    case 'orchestrator':
      return 'Orchestrator';
    case 'knowledge_graph':
      return 'Knowledge Graph Agent';
    case 'text_entity':
      return 'Plant Name Resolution';
    case 'image_understanding':
      return 'Image Understanding';
    case 'specialist':
      return 'Specialist Agent';
    case 'retrieve_plant_graph':
      return 'Plant Graph Retrieval';
    case 'resolve_plant_names':
      return 'Plant Name Resolution';
    case 'inspect_uploaded_image':
      return 'Image Classifier';
    default:
      return clean
        .replace(/[_-]+/g, ' ')
        .replace(/\b\w/g, c => c.toUpperCase());
  }
}

/**
 * Translates technical transition types into readable phrases.
 */
export function formatTransitionType(raw: string | null | undefined): string {
  if (!raw) return 'Transitioned';
  const clean = raw.trim().toLowerCase();

  switch (clean) {
    case 'subagent_delegation':
      return 'Delegated the request';
    case 'subagent_handoff':
      return 'Returned control to the orchestrator';
    case 'graph_node_transition':
      return 'Moved to the next stage';
    case 'graph_conditional_edge':
      return 'Selected the next step';
    case 'tool_selection':
      return 'Selected retrieval tool';
    default:
      return raw.trim().replace(/[_-]+/g, ' ');
  }
}

/**
 * Resolves the source and destination titles for a given routing step.
 */
export function getStepTitle(step: RoutingStep): { from: string; to: string; combined: string } {
  const type = (step.routing_type || '').toLowerCase();

  if (type === 'subagent_delegation') {
    let subagent = step.to_subagent;
    if ((!subagent || subagent === 'specialist') && step.details) {
      const desc = JSON.stringify(step.details);
      if (desc.includes('knowledge_graph')) subagent = 'knowledge_graph';
      else if (desc.includes('text_entity')) subagent = 'text_entity';
      else if (desc.includes('image_understanding')) subagent = 'image_understanding';
    }
    const from = formatNodeLabel(step.from_agent || 'orchestrator');
    const to = formatNodeLabel(subagent || 'Specialist');
    return { from, to, combined: `${from} → ${to}` };
  }

  if (type === 'subagent_handoff') {
    let subagent = step.from_subagent;
    if ((!subagent || subagent === 'specialist') && step.details) {
      const desc = JSON.stringify(step.details);
      if (desc.includes('knowledge_graph')) subagent = 'knowledge_graph';
      else if (desc.includes('text_entity')) subagent = 'text_entity';
      else if (desc.includes('image_understanding')) subagent = 'image_understanding';
    }
    const from = formatNodeLabel(subagent || 'Specialist');
    const to = formatNodeLabel(step.to_agent || 'orchestrator');
    return { from, to, combined: `${from} → ${to}` };
  }

  if (type === 'tool_selection') {
    const from = formatNodeLabel(step.from_subagent || step.from_agent || 'knowledge_graph');
    const to = formatNodeLabel(step.to_tool || 'tool');
    return { from, to, combined: `${from} → ${to}` };
  }

  if (type === 'graph_node_transition') {
    const from = formatNodeLabel(step.from_node || 'START');
    const to = formatNodeLabel(step.to_node || 'deep_orchestrator');
    return { from, to, combined: `${from} → ${to}` };
  }

  if (type === 'graph_conditional_edge') {
    const from = formatNodeLabel(step.from_node || 'deep_orchestrator');
    const to = formatNodeLabel(step.to_node || 'END');
    return { from, to, combined: `${from} → ${to}` };
  }

  // Fallback for custom or unexpected transitions
  const from = formatNodeLabel(step.from_node || step.from_agent || step.from_subagent || '');
  const to = formatNodeLabel(step.to_node || step.to_subagent || step.to_tool || step.to_agent || '');
  if (from && to && from !== 'Unknown' && to !== 'Unknown') {
    return { from, to, combined: `${from} → ${to}` };
  }
  const single = to !== 'Unknown' ? to : from !== 'Unknown' ? from : 'Routing Step';
  return { from: single, to: single, combined: single };
}

/**
 * Cleans the recorded decision string so it is friendly and free of raw internals.
 */
export function cleanDecision(decision: string | null | undefined): string {
  if (!decision) return '';
  let text = String(decision).trim();

  // Strip wrapping quotes if stringified
  if ((text.startsWith('"') && text.endsWith('"')) || (text.startsWith("'") && text.endsWith("'"))) {
    text = text.slice(1, -1).trim();
  }

  // Guard against any accidental secrets or internal tokens
  if (/password|secret|token|api_key/i.test(text)) {
    return 'Routing transition recorded.';
  }

  return text;
}
