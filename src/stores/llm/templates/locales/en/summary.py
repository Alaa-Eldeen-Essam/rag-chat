from string import Template

#### SUMMARY PROMPTS ####

#### System ####
system_prompt = Template("\n".join([
    "You are an expert writing assistant.",
    "Condense the provided content into a clear, faithful summary.",
    "Preserve factual accuracy and note any missing context when necessary.",
    "Respond in the same language as the source material whenever possible.",
]))

#### Document ####
document_prompt = Template(
    "\n".join([
        "## Document: $doc_label",
        "$chunk_text",
    ])
)

#### Summary ####
summary_prompt = Template("\n".join([
    "Summarize the following documents. Focus on the reader instructions at the end if provided.",
    "",
    "$documents",
    "",
    "## Instructions:",
    "$focus",
    "",
    "## Summary:",
]))

default_focus = Template("Provide a concise summary that highlights the key ideas and critical details.")
