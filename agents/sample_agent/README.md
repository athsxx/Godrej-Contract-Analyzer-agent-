# Sample agent scaffold

Use this folder as the starting point for a new conversational agent. Rename `sample_agent` to your agent name and update the code before shipping.

What to fill:
- `chat_agent.py`: plug in your ingestion (PDF/DOCX extraction, chunking), embeddings/indexing, and Claude 3.7 Sonnet Bedrock calls. Keep credentials in env vars.
- Update `ALLOWED_EXTENSIONS`, `MAX_UPLOAD_FILES`, and size limits as needed.
- Replace the default Bedrock model ARN if your region/version differs.
- If you store files elsewhere (e.g., S3), adjust `_save_upload` and state export/restore.

Flow:
1) Validate + store uploads → extract text (fallback to images for PDFs).
2) Build retrieval context → call `call_bedrock_chat` with text + optional image bytes.
3) Return chat history + answer for rendering in the workspace template.

Keep any external callbacks HTTPS-only to match the deployed app. Test locally with `python3 manage.py runserver 127.0.0.1:8501` once you have wired the view/template.
