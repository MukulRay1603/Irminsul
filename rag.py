import os
import logging

import torch
from dotenv import load_dotenv

load_dotenv()

from langchain_classic.chains import RetrievalQA
from langchain_core.prompts import PromptTemplate
from langchain_community.embeddings import HuggingFaceEmbeddings
from langchain_community.vectorstores import Pinecone as LangchainPinecone
from pinecone import Pinecone

logger = logging.getLogger(__name__)

LLM_BACKEND      = os.getenv("LLM_BACKEND", "groq")
LOCAL_MODEL      = os.getenv("MODEL_PATH", "./models/merged/exp2_lr2e-4_r16")
EMBED_MODEL      = os.getenv("EMBED_MODEL", "sentence-transformers/all-MiniLM-L6-v2")
PINECONE_API_KEY = os.getenv("PINECONE_API_KEY")
PINECONE_INDEX   = os.getenv("PINECONE_INDEX", "llmops-rag")
GROQ_API_KEY     = os.getenv("GROQ_API_KEY")
GROQ_MODEL       = "llama-3.1-8b-instant"

PROMPT_TEMPLATE = """You are a knowledgeable Genshin Impact assistant. \
Answer using ONLY the context provided below. If the context does not \
contain enough information to answer confidently, say so — do not invent \
weapon names, artifact sets, or lore details.

Context:
{context}

Question: {question}

Answer:"""


def _build_groq_llm():
    from langchain_groq import ChatGroq

    if not GROQ_API_KEY:
        raise EnvironmentError("GROQ_API_KEY not set in environment.")

    logger.info(f"Using Groq backend — model: {GROQ_MODEL}")
    return ChatGroq(
        api_key=GROQ_API_KEY,
        model_name=GROQ_MODEL,
        temperature=0.2,
        max_tokens=512,
    )


def _build_local_llm():
    from transformers import (
        AutoModelForCausalLM,
        AutoTokenizer,
        BitsAndBytesConfig,
        pipeline,
    )
    from langchain_community.llms import HuggingFacePipeline

    logger.info(f"Loading local model from {LOCAL_MODEL}")

    bnb_config = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_compute_dtype=torch.bfloat16,
        bnb_4bit_use_double_quant=True,
    )

    tokenizer = AutoTokenizer.from_pretrained(LOCAL_MODEL)
    tokenizer.pad_token = tokenizer.eos_token

    model = AutoModelForCausalLM.from_pretrained(
        LOCAL_MODEL,
        quantization_config=bnb_config,
        device_map="auto",
        torch_dtype=torch.bfloat16,
        max_memory={0: "5.5GiB", "cpu": "24GiB"},
    )
    model.eval()

    hf_pipe = pipeline(
        "text-generation",
        model=model,
        tokenizer=tokenizer,
        max_new_tokens=256,
        do_sample=False,
        temperature=None,
        top_p=None,
        repetition_penalty=1.3,
        return_full_text=False,
        eos_token_id=tokenizer.eos_token_id,
        pad_token_id=tokenizer.eos_token_id,
    )

    logger.info("Local model loaded.")
    return HuggingFacePipeline(pipeline=hf_pipe)


class RAGChain:
    def __init__(self):
        self.ready = False
        self.chain = None
        self.vectorstore = None

    def load(self):
        llm = _build_groq_llm() if LLM_BACKEND == "groq" else _build_local_llm()

        logger.info("Connecting to Pinecone...")
        embeddings = HuggingFaceEmbeddings(model_name=EMBED_MODEL)
        pc = Pinecone(api_key=PINECONE_API_KEY)
        index = pc.Index(PINECONE_INDEX)
        self.vectorstore = LangchainPinecone(index, embeddings, "text")
        logger.info("Pinecone connected.")

        prompt = PromptTemplate(
            template=PROMPT_TEMPLATE,
            input_variables=["context", "question"],
        )
        self.chain = RetrievalQA.from_chain_type(
            llm=llm,
            chain_type="stuff",
            retriever=self.vectorstore.as_retriever(search_kwargs={"k": 3}),
            return_source_documents=True,
            chain_type_kwargs={"prompt": prompt},
        )
        self.ready = True
        logger.info(f"RAG chain ready — backend: {LLM_BACKEND}")

    def query(self, question: str, top_k: int = 3) -> tuple[str, list[str]]:
        if not self.ready:
            raise RuntimeError("RAG chain is not loaded.")

        self.chain.retriever.search_kwargs["k"] = top_k
        result = self.chain.invoke({"query": question})
        answer = result["result"].strip().replace("</s>", "").strip()
        sources = [
            doc.metadata.get("source", "unknown")
            for doc in result.get("source_documents", [])
        ]
        return answer, list(dict.fromkeys(sources))