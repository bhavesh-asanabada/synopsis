# Synopsis chat

Open the **Ask Synopsis** button at the bottom right for a compact conversation, or **Chat workspace** in the sidebar for the full workspace. Expanding or minimizing preserves the conversation, draft, and file selection. The message area scrolls independently of the composer.

## Ask about documents

Use **Choose files** to select up to 30 library documents. **Add files** uploads new documents through the existing extraction/OCR workflow; wait for processing before sending a question. You can also drop files into chat. Only selected documents are searched. With no files selected, questions use general model knowledge and optional web search.

Answers show source excerpts and document/page links. Follow-up questions include bounded conversation history; removing a file excludes earlier turns involving that file from the next model request. Retrieval selects relevant passages, not every page of every selected document. Source IDs and exact quotations are checked, but this cannot establish whether the model's interpretation is correct.

Conversations are saved locally. Use the conversation selector to reopen one, **Export** for a self-contained JSON copy including generated artifacts, or **Delete chat** to remove it after confirmation. Library ZIP backups also include conversations and artifacts. A document cited by a saved conversation is protected from permanent deletion until that conversation is removed.

## Configure models and tools

Open **Settings & backup**, or **Settings** inside chat. Configure and enable the text model under **AI model**, then expand **Chat images & web search** for the additional options. Save preferences when finished.

- **Text and architecture:** the saved Chat Completions-compatible endpoint and model are used for answers and structured architecture generation. **Test model** checks a small synthetic request. Without an enabled text model, chat can return local document or web excerpts, but cannot synthesize answers or diagrams.
- **Images:** enable image generation and supply an image API URL, model identifier, and any required key. When the image and text endpoints match exactly, the image provider can reuse the text provider key. The connector calls `/images/generations` and requires a base64 image response. Enable the base64 response-format option only when the provider requires it; GPT image models return base64 without that parameter. URL-only image responses are unsupported. This generates new images from prompts and selected source context; it does not edit an uploaded image.
- **Web search:** enable search and enter a Brave Search API key. Then check **Search web** in the composer for each request that should search. The question is sent to Brave; selected document text is not sent to the search service. Results are search excerpts with links and retrieval timestamps, not full fetched webpages. The enabled text model can synthesize these excerpts together with selected document passages.

The image connector follows the [image generation API contract](https://developers.openai.com/api/reference/resources/images/methods/generate). Search uses the [Brave Web Search API](https://api-dashboard.search.brave.com/app/documentation/web-search). Provider compatibility and credentials are required; the application does not include an API subscription.

Keys remain in the local SQLite database, unencrypted, and are not returned to the browser or included in exported backups. Optional environment fallbacks are `SYNOPSIS_AI_API_KEY`, `SYNOPSIS_IMAGE_API_KEY`, and `SYNOPSIS_WEB_SEARCH_KEY`. Restored text, image, and web configurations are disabled until re-enabled. External model requests send your question, relevant selected passages, and bounded eligible conversation history to the configured provider.

## Images and architecture

Choose **Generate image** or **Architecture diagram** in the mode selector. **Auto** also recognizes explicit image/diagram creation requests. For follow-up changes to a diagram, keep Architecture diagram selected and describe the changes.

Images can be downloaded as PNG. Architecture responses contain named components, layers/groups, and labeled connections. Zoom the diagram, inspect **Components & connections**, and download SVG or the underlying JSON. Diagrams support up to 12 groups, 60 components, and 120 connections. Synopsis validates the structure and renders escaped, passive SVG locally; it does not execute model-generated markup or code. Layout is automatic and the proposed architecture needs technical review.

The workspace is part of the current single-user local application. It does not provide separate customer accounts or shared conversations. Provider failures preserve the draft and do not save an incomplete message pair. Automated tests use controlled provider responses; actual external model, search, and image quality require evaluation with your configured services.
