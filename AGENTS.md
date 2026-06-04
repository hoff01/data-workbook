# Agent Instructions

- Always use Context7 when library/API documentation, code generation, setup steps, or configuration guidance are needed, even if the user does not explicitly ask for it.
- Use Headroom for large-context agent workflows. When tool outputs, logs, tables, docs, search results, or file reads are bulky enough to risk wasting context, prefer Headroom-style compression/retrieval before carrying that content forward. Use the downloaded repo at `vendor/headroom`, the official docs at `https://headroom-docs.vercel.app/docs`, and Context7 ID `/chopratejas/headroom` as the source of truth for Headroom setup or integration. Skip Headroom for small outputs or when no local Headroom process/package is available and the task does not need compression.
- Do not run rendered browser checks for every small dashboard edit. Use browser validation only when the user explicitly asks for it, when the change is a meaningful frontend/UI behavior change, or when a rendered check is needed to confirm the fix.
- Keep responses concise and focused on the code, files changed, and verification results.
