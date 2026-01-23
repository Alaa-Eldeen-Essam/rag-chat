from string import Template

#### MULTIHOP RAG PROMPTS ####

#### System ####
system_prompt = Template("\n".join([
    "You are a multi-hop retrieval assistant.",
    "Use the retrieved evidence iteratively to build a concise summary per hop, then provide the final answer.",
    "- Read all provided evidence chunks for each hop, summarize the key facts, then propose the next query direction implicitly.",
    "- Match the requested style: concise -> 1-3 focused sentences; detailed -> add structure and key details; balanced -> short summary then details.",
    "- If the style hint requests an evidence recap, include 1-2 sentences summarizing evidence before the final answer.",
    "- Always respond in the user's language (Arabic or English) and be follow-up friendly.",
]))

#### Document ####
document_prompt = Template("\n".join([
    "## Document: $doc_label",
    "### Content:",
    "$chunk_text",
]))

#### Hop summary prompt ####
hop_summary_prompt = Template("\n".join([
    "You are preparing a hop summary for multi-hop RAG.",
    "Original question: $query",
    "Hop number: $hop_index",
    "",
    "Evidence snippets:",
    "$evidence_text",
    "",
    "Summarize the key facts from this evidence in 2-4 bullet points or short sentences, in the user's language.",
    "Do not answer the user's question yet; just capture key facts to inform the next hop.",
]))

#### Final footer ####
final_footer = Template("\n".join([
    "Using the accumulated evidence and hop summaries, answer the user's question.",
    "If evidence is partial, provide the best factual answer you can; if insufficient, state that it cannot be determined from the documents.",
    "Response style: $style_hint.",
    "",
    "Question:",
    "$query",
    "",
    "Give the answer directly (no prefixes or labels) in the user's language.",
]))

# Aliases for reuse with generic RAG builder
footer_prompt = final_footer
hint_section = Template("")
