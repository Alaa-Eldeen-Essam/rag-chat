from string import Template

#### SUMMARY PROMPTS ####

#### System ####
system_prompt = Template("\n".join([
    "You are an expert summarization assistant.",
    "Your only job is to write neutral, factual summaries of documents.",
    "Focus on who, what, when, where, why, and how; emphasize the core events and outcomes.",
    "Do not critique the writing, tone, or style, and do not comment on how good or bad a passage is.",
    "Never address the author or the user directly; do not say things like 'your passage' or 'this summary'.",
    "Respond in the language implied by the configuration or explicit instructions, not by the document headings.",
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
    "Summarize the following documents into a single, coherent paragraph or a few short paragraphs.",
    "Write a neutral, factual summary of the content. If the text is narrative or literary, focus on plot events and important factual context, not on analysis or critique.",
    "Use the instructions (if any) as guidance, but do not restate them, and do not evaluate or compare different summaries.",
    "",
    "$documents",
    "",
    "Instructions for the model (not to be echoed to the user):",
    "$focus",
    "",
    "Now write only the final summary text for the reader.",
    "Do not include headings, labels such as 'Summary:' or 'Reader Instructions:', and do not add meta commentary about the passage or summary quality.",
]))

default_focus = Template("Provide a concise summary that highlights the key ideas and critical details.")
