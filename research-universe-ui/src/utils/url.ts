const ALLOWED_PROTOCOLS = /^https?:\/\//i;

export function safeUrl(url: string | undefined | null): string | undefined {
  if (!url) return undefined;
  return ALLOWED_PROTOCOLS.test(url.trim()) ? url.trim() : undefined;
}

// Strip leading sort-order prefix from category names stored in DB
// e.g. "01. Raw Materials & Critical Minerals" → "Raw Materials & Critical Minerals"
export function catName(name: string): string {
  return name.replace(/^\d+\.\s*/, '');
}
