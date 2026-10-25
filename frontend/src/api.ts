export type Stage = 'new' | 'saved' | 'applied' | 'interview' | 'offer' | 'rejected' | 'archived';
export type Job = {
  id: number; source_id: number; company: string; title: string; location: string; url: string;
  description: string; categories: string[]; seniority: string; seniority_tags: string[]; work_mode: string;
  language_tags: string[]; platform_tags: string[]; requirement_tags: string[]; affirmative_tags: string[];
  location_fit: string; hidden: boolean; favorite: boolean; active: boolean; stage: Stage; notes: string;
  first_seen: string; last_seen: string; updated_at: string | null;
};
export type Source = {
  id: number; name: string; board: string; enabled: number;
  last_success: string | null; last_error: string | null; job_count: number;
};
export type Run = {
  id: number; company: string; status: string; count: number;
  started_at: string; error: string | null;
};
export type Revision = { id: number; recorded_at: string; description: string };
export const stages: Record<Stage, string> = {
  new: 'Não iniciada', saved: 'Tenho interesse', applied: 'Candidatura enviada',
  interview: 'Em entrevistas', offer: 'Proposta recebida', rejected: 'Encerrada pela empresa',
  archived: 'Arquivada por mim',
};

export async function api<T>(path: string, method = 'GET', body?: unknown): Promise<T> {
  const response = await fetch(`/api${path}`, {
    method,
    headers: body === undefined ? {} : { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!response.ok) {
    let detail = '';
    try {
      const payload = await response.json();
      if (typeof payload.detail === 'string') detail = payload.detail;
    } catch { /* Non-JSON error from the development proxy. */ }
    throw new Error(detail || `Não foi possível concluir a operação (${response.status}). Verifique o backend.`);
  }
  return response.json();
}
