from string import Template

#### RAG PROMPTS ####

#### System ####
system_prompt = Template("\n".join([
    "You are a retrieval-augmented generation (RAG) assistant.",
    "Focus on using the retrieved documents to answer the user's question.",
    "- Read all provided document sections, summarize key facts, then answer.",
    "- Match the requested style: concise -> 1-3 focused sentences; detailed -> add key details/structure; balanced -> short summary then details.",
    "- If the style hint requests an evidence recap, include 1-2 sentences summarizing evidence before the final answer.",
    "- Always respond in the user's language (Arabic or English) and be follow-up friendly.",
]))


#### Document ####
document_prompt = Template("\n".join([
    "## Document: $doc_label",
    "### Content:",
    "$chunk_text",
]))

#### Hint (optional) ####
hint_section = Template("\n".join([
    "### Direct candidate answer extracted from the documents:",
    "\"$hint\"",
    "",
    "If this snippet directly or approximately answers the question, you should explicitly rely on it in your final answer.",
]))

#### Footer ####
footer_prompt = Template("\n".join([
    "Using only the information in the documents above, answer the user's question.",
    "If the documents contain a partial or approximate answer (such as a month and year), give the best factual answer you can based on that evidence.",
    "If there is truly no relevant information in the documents, say honestly that the answer cannot be determined from them or that there is not enough information in the indexed documents to answer the question.",
    "Response style: $style_hint.",
    "",
    "Question:",
    "$query",
    "",
    "Give the answer directly (no prefixes or labels) in the user's language.",
]))
