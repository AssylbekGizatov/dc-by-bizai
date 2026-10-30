export type TicketStatus = 'pending' | 'reviewed' | 'escalated' | 'simulated_sent'
export type Priority = 'p0' | 'p1' | 'p2' | 'p3'
export interface Rule {
  id: string; ref: string; title: string; text: string; section: string; source: string; synthetic: boolean; score?: number
}
export interface TriageResult {
  lang: string; category: string; priority: Priority; is_spam_or_duplicate: boolean
  extracted: { nickname: string | null; rule_refs: string[]; has_evidence: boolean; server: string | null }
  draft_reply: { lang: string; text: string; cited: string[] }
  needs_human: boolean; confidence: number; reasons: string[]
}
export interface Diagnostics {
  language_method?: string; classifier_method?: string; retrieval_method?: string; generation_mode?: string
  normalizations?: string[]; warnings?: string[]; timings_ms?: Record<string, number>
  tokens?: {input: number; output: number}; estimated_cost_usd?: number | null; cache_hit?: boolean
}
export interface Ticket {
  id: string; text: string; normalized_text: string; kind: 'complaint' | 'report'; created_at: string
  status: TicketStatus; player_id: string | null; server: string | null; attachments_count: number
  result: TriageResult; citations: Rule[]; reviewer_note: string; draft_reply: string; diagnostics: Diagnostics; revision: number
}
export interface TicketList { items: Ticket[]; total: number }
export interface Health {
  status: string; mode: string; auth_required: boolean; rules_count: number; real_rules_loaded: boolean; generation_mode: string
}
export interface CreateTicket {
  text: string; kind: 'complaint' | 'report'; player_id?: string; server?: string; attachments_count?: number; server_lang?: string
}
export interface Filters { status: string; category: string; language: string; priority: string; search: string }
export interface Review { draft_reply?: string; status?: TicketStatus; reviewer_note?: string; expected_revision: number }
