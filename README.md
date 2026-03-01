# AI Travel Concierge – RAG Chatbot

## Internship Project – Agentic AI Saksham (Track A)

This project is developed as part of the Agentic AI Saksham Internship program.

In Week 1, we built a basic Retrieval-Augmented Generation (RAG) chatbot that allows users to upload documents and ask questions based on the document content.

---

## Project Objective

The goal of this project is to build an AI Travel Concierge that:

- Accepts travel-related documents
- Understands document content
- Answers user queries based only on uploaded documents
- Uses semantic search instead of keyword search

---

## Features Implemented (Week 1)

- Upload support for:
  - PDF
  - TXT
  - CSV
  - DOCX
  - XLSX
  - Images (OCR using Tesseract)

- Document chunking using RecursiveCharacterTextSplitter
- Local embeddings using HuggingFace model (all-MiniLM-L6-v2)
- Vector storage using FAISS
- Context-based answer generation using Google Gemini (gemini-2.5-flash)
- Streamlit web interface

---

## How the System Works

1. User uploads a document.
2. The document is split into smaller text chunks.
3. Each chunk is converted into embeddings.
4. Embeddings are stored in FAISS vector database.
5. When a question is asked:
   - Relevant chunks are retrieved using similarity search.
   - Retrieved context is sent to Gemini.
   - Gemini generates an answer based only on that context.

This prevents hallucination and ensures grounded responses.

---

## Tech Stack

- Python
- LangChain (1.x)
- Streamlit
- FAISS
- HuggingFace Sentence Transformers
- Google Gemini API
- Tesseract OCR

---

## Project Structure

```
AI_Travel_Concierge/
│
├── app.py
├── requirements.txt
├── README.md
├── .gitignore
```

---

## Setup Instructions (Local)

### 1. Create Virtual Environment

```bash
python -m venv venv
```

### 2. Activate Environment

Windows:

```bash
venv\Scripts\activate
```

### 3. Install Dependencies

```bash
pip install -r requirements.txt
```

### 4. Create .env File

Create a file named `.env` and add:

```
GOOGLE_API_KEY=your_api_key_here
```

### 5. Run Application

```bash
streamlit run app.py
```

---

## Current Status

Week 1:
- Basic RAG chatbot completed
- Working locally
- GitHub repository created
- Deployment in progress

---

## Upcoming Improvements (Week 2)

- Deploy on Streamlit Cloud
- Improve UI
- Add better error handling
- Prepare demo video
- Start tool integration for Agent architecture