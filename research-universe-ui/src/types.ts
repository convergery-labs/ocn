export interface User {
  id: string;
  name: string;
  email: string;
}

export interface Company {
  id: string;
  company_name: string;
  ticker: string;
  market: string;
  country: string;
  website: string;
  categories: string[];
  subcategories: string[];
  proposed_subcategories?: string[] | null;
  status: 'pending_review' | 'verified';
  agent_added: boolean;
  added_by: string;
  added_at: string;
  verified_by?: string | null;
  verified_at?: string | null;
  multi_category_reason?: string | null;
}

export interface Category {
  id: number;
  name: string;
  type: string;
}

export interface ChatMessage {
  id: string;
  role: 'user' | 'agent';
  text: string;
  cardType?: string | null;
  cardData?: Record<string, unknown> | null;
  timestamp: Date;
}

export interface ChatResponse {
  message: string;
  card_type: string | null;
  card_data: Record<string, unknown> | null;
  conversation_id: string;
}

export interface ScanJob {
  job_id: string;
  status: 'running' | 'completed' | 'failed';
  categories_done: number;
  companies_proposed: number;
  companies_skipped: number;
  category_results: Array<{
    category_id: number;
    category_name: string;
    proposed: number;
    skipped: number;
  }>;
}

export interface ScheduleSummary {
  last_run_at: string | null;
  next_run_at: string | null;
}

export type Tab = 'chat' | 'pending' | 'discovery';
