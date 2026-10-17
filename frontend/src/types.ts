export type Candidate = {
  plant_id: string;
  label: string;
  confidence: number;
  match_method?: string | null;
  matched_name?: string | null;
  language?: string | null;
  alias_type?: string | null;
};

export type Clarification = {
  clarification_id: string;
  question: string;
  candidates: Candidate[];
};

export type FinalResponse = {
  text: string;
  citation_ids: string[];
  placeholder: boolean;
  provider: string;
  model?: string | null;
  fallback_used: boolean;
};

export type ChatState = {
  mode: 'discovery' | 'conversation';
  status: string;
  active_plant: Candidate | null;
  clarification: Clarification | null;
  response: FinalResponse | null;
  session_notice: string;
  understanding?: { candidates?: Candidate[]; limitations?: string[]; needs_clarification?: boolean } | null;
  image_understanding?: { candidates?: Candidate[]; limitations?: string[]; needs_clarification?: boolean } | null;
};

export type Session = {
  session_id: string;
  title: string;
  archived: boolean;
  created_at: string;
  updated_at: string;
  state: ChatState;
};

export type Page<T> = { items: T[]; next_offset: number | null };

export type Message = {
  message_id: string;
  operation_id: string;
  role: 'user' | 'assistant';
  content: string;
  status: string;
  data: Record<string, unknown>;
  created_at: string;
};

export type Run = {
  operation_id: string;
  session_id: string;
  status: 'accepted' | 'running' | 'interrupted' | 'complete' | 'cancelled' | 'failed';
  result: ChatState | null;
  error_code: string | null;
  events_url: string;
};

export type ImageReference = {
  image_id: string;
  metadata: { mime_type: string; size_bytes: number; width: number; height: number };
};

export type Evidence = {
  evidence_id: string;
  modality: 'text' | 'image' | 'graph';
  claim: string;
  evidence_type: string;
  confidence: number;
  provenance: { source_id: string; source_type: string; reference: string };
  source_urls?: string[];
  graph_path?: string[];
  graph_nodes?: Record<string, unknown>[];
};

export type Event = {
  version: 1;
  operation_id: string;
  sequence: number;
  type: string;
  payload: Record<string, unknown>;
};

export type Capabilities = {
  image_upload: boolean;
  image_classifier: boolean;
  image_scope: string;
  max_image_bytes: number;
  streaming: string;
  one_plant_per_session: boolean;
  llm_provider: string;
};
