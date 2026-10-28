/** The four kinds of visitor CrawlDoctor separates, with the hub's series colours. */
export type VisitorKind = "human" | "ai" | "search" | "bot"

export const KIND_META: Record<VisitorKind, { label: string; plural: string; color: string }> = {
  human: { label: "Human", plural: "Humans", color: "var(--series-1)" },
  ai: { label: "AI crawler", plural: "AI crawlers", color: "var(--series-2)" },
  search: { label: "Search engine", plural: "Search engines", color: "var(--series-3)" },
  bot: { label: "Other bot", plural: "Other bots", color: "var(--series-gray)" },
}

export const KIND_ORDER: VisitorKind[] = ["human", "ai", "search", "bot"]

const AI = /gpt|openai|claude|anthropic|perplexity|extended|edgegpt|ccbot|bytespider|cohere|meta-external|diffbot|youbot|ai2bot|amazonbot|mistral|gemini/i
const SEARCH = /google|bing|yandex|duckduck|baidu|slurp|applebot|petal|seznam|naver/i

/** Sorts a crawler label (e.g. "GPTBot", "GoogleBot", "Human") into a kind. */
export function visitorKind(label: string | null | undefined, isBot?: boolean | null): VisitorKind {
  const l = (label || "").trim()
  if (!l || /^human$/i.test(l) || /^unknown$/i.test(l)) return isBot ? "bot" : "human"
  if (AI.test(l)) return "ai"
  if (SEARCH.test(l)) return "search"
  return isBot === false ? "human" : "bot"
}
