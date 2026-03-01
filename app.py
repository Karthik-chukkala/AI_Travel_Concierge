import os
import streamlit as st
import pytesseract
from PIL import Image
from dotenv import load_dotenv

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_community.vectorstores import FAISS
from langchain_community.document_loaders import (
    PyPDFLoader,
    TextLoader,
    CSVLoader,
    UnstructuredWordDocumentLoader,
    UnstructuredExcelLoader,
)
from langchain_community.embeddings import HuggingFaceEmbeddings


# -----------------------------
# Load environment variables
# -----------------------------
load_dotenv()
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")

if not GOOGLE_API_KEY:
    st.error("GOOGLE_API_KEY not found. Please check your .env file.")
    st.stop()


# -----------------------------
# Configure OCR (local)
# -----------------------------
pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"


# -----------------------------
# Initialize LLM (Gemini)
# -----------------------------
llm = ChatGoogleGenerativeAI(
    model="gemini-2.5-flash",
    temperature=0.3,
    google_api_key=GOOGLE_API_KEY,
)


# -----------------------------
# Local Embeddings (Free)
# -----------------------------
embeddings = HuggingFaceEmbeddings(
    model_name="all-MiniLM-L6-v2"
)


# -----------------------------
# Document Loader
# -----------------------------
def load_documents(uploaded_file):

    extension = os.path.splitext(uploaded_file.name)[1].lower()

    os.makedirs("temp", exist_ok=True)
    temp_path = os.path.join("temp", uploaded_file.name)

    with open(temp_path, "wb") as f:
        f.write(uploaded_file.getbuffer())

    if extension == ".pdf":
        loader = PyPDFLoader(temp_path)
        return loader.load()

    elif extension == ".txt":
        loader = TextLoader(temp_path, encoding="utf-8")
        return loader.load()

    elif extension == ".csv":
        loader = CSVLoader(temp_path)
        return loader.load()

    elif extension in [".docx", ".doc"]:
        loader = UnstructuredWordDocumentLoader(temp_path)
        return loader.load()

    elif extension in [".xlsx", ".xls"]:
        loader = UnstructuredExcelLoader(temp_path)
        return loader.load()

    elif extension in [".png", ".jpg", ".jpeg"]:
        image = Image.open(temp_path)
        text = pytesseract.image_to_string(image)
        return [Document(page_content=text)]

    else:
        return None


# -----------------------------
# Streamlit UI
# -----------------------------
st.set_page_config(page_title="AI Travel Concierge")
st.title("AI Travel Concierge - RAG Chatbot")

uploaded_file = st.file_uploader(
    "Upload a document",
    type=["pdf", "txt", "csv", "docx", "doc", "xlsx", "xls", "png", "jpg", "jpeg"],
)

if uploaded_file:

    with st.spinner("Processing document..."):
        documents = load_documents(uploaded_file)

        if not documents:
            st.error("Unsupported file type.")
            st.stop()

        splitter = RecursiveCharacterTextSplitter(
            chunk_size=1000,
            chunk_overlap=200,
        )

        chunks = splitter.split_documents(documents)

        vectorstore = FAISS.from_documents(chunks, embeddings)
        retriever = vectorstore.as_retriever()

    st.success("Document processed successfully.")

    query = st.text_input("Ask a question about the document")

    if query:
        with st.spinner("Generating answer..."):

            relevant_docs = retriever.invoke(query)

            context = "\n\n".join(
                doc.page_content for doc in relevant_docs
            )

            prompt = f"""
You are a document-based question answering assistant.

Use only the provided context to answer the question.
If the answer is not present, say:
"Information not found in the document."

Context:
{context}

Question:
{query}
"""

            response = llm.invoke(prompt)

            st.subheader("Answer")
            st.write(response.content)