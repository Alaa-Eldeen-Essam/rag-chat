from string import Template

#### MULTIHOP RAG PROMPTS ####

#### System ####
system_prompt = Template("\n".join([
    "You are a multi-hop retrieval assistant.",
    "Use the retrieved evidence iteratively to build a concise summary per hop, then provide the final answer.",
    "- Read all provided evidence chunks for each hop, summarize the key facts, then propose the next query direction implicitly.",
    "- Resolve references from recent chat context first (pronouns, omitted entities), then ground facts in evidence.",
    "- Match the requested style: concise -> 1-3 focused sentences; detailed -> add structure and key details; balanced -> short summary then details.",
    "- If the style hint requests an evidence recap, include 1-2 sentences summarizing evidence before the final answer.",
    "- If evidence contains multiple similar/conflicting candidates, ask a clarification question instead of guessing.",
    "- Answer in the same language as the user's question and be follow-up friendly.",
]))

analysis_system_prompt = Template("\n".join([
    "You are an evidence analyst for multi-hop RAG.",
    "Use accumulated evidence and hop summaries to produce strict JSON only.",
    "Do not add markdown or prose outside JSON.",
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

analysis_footer_prompt = Template("\n".join([
    "Conversation intent context:",
    "$conversation_context",
    "",
    "User question:",
    "$query",
    "",
    "Return strict JSON with keys:",
    "resolved_question, evidence_facts, candidate_answers, ambiguity_detected, ambiguity_reason, clarification_question, clarification_options, answer_confidence.",
    "If multiple close candidates exist, mark ambiguity_detected=true and provide a good clarification question.",
]))

#### Final footer ####
final_footer = Template("\n".join([
    "Using the accumulated evidence and hop summaries, answer the user's question.",
    "If evidence is partial, provide the best factual answer you can; if insufficient, state that it cannot be determined from the documents.",
    "Conversation intent context:",
    "$conversation_context",
    "",
    "Evidence analysis summary:",
    "$analysis_summary",
    "",
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
