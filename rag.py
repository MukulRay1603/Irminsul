import os
import logging
import torch
from dotenv import load_dotenv

load_dotenv() 

from transformers import AutoTokenizer, AutoModelForCausalLM, pipeline, BitsAndBytesConfig
from langchain_community.vectorstores import Pinecone as LangchainPinecone
from langchain_community.embeddings import HuggingFaceEmbeddings
from langchain.chains import RetrievalQA
from langchain_community.llms import HuggingFacePipeline
from langchain.prompts import PromptTemplate
from pinecone import Pinecone

logger = logging.getLogger(__name__)

LOCAL_MODEL = os.getenv("MODEL_PATH", "./models/merged/exp2_lr2e-4_r16")
EMBED_MODEL = os.getenv("EMBED_MODEL", "sentence-transformers/all-MiniLM-L6-v2")
PINECONE_API_KEY = os.getenv("PINECONE_API_KEY")
PINECONE_INDEX = os.getenv("PINECONE_INDEX", "llmops-rag")

PROMPT_TEMPLATE = """You are a precise Genshin Impact assistant. Answer ONLY using the context below.
If specific details like weapon names or artifact sets are not in the context, say so — do not invent them.

Context:
{context}

Question: {question}

Answer (use only information from the context above):"""


class RAGChain:
    def __init__(self):
        self.ready = False
        self.chain = None
        self.vectorstore = None

    def load(self):
        logger.info(f"Loading model from {LOCAL_MODEL}")

        # ---- 4-bit quant for 6GB VRAM ----
        bnb_config = BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_quant_type="nf4",
            bnb_4bit_compute_dtype=torch.bfloat16,
            bnb_4bit_use_double_quant=True,
        )

        tokenizer = AutoTokenizer.from_pretrained(LOCAL_MODEL)
        model = AutoModelForCausalLM.from_pretrained(
            LOCAL_MODEL,
            quantization_config=bnb_config,
            device_map="auto",
            torch_dtype=torch.bfloat16,
            max_memory={0: "5.5GiB", "cpu": "24GiB"},
        )
        model.eval()

        tokenizer.pad_token = tokenizer.eos_token

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
        llm = HuggingFacePipeline(pipeline=hf_pipe)
        logger.info("Model loaded.")

        # ---- Embeddings + Pinecone ----
        logger.info("Connecting to Pinecone...")
        embeddings = HuggingFaceEmbeddings(model_name=EMBED_MODEL)
        pc = Pinecone(api_key=PINECONE_API_KEY)
        index = pc.Index(PINECONE_INDEX)
        self.vectorstore = LangchainPinecone(index, embeddings, "text")
        logger.info("Pinecone connected.")

        # ---- RetrievalQA chain ----
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
        logger.info("RAG chain ready.")

    def query(self, question: str, top_k: int = 3, max_new_tokens: int = 512) -> tuple[str, list[str]]:
        if not self.ready:
            raise RuntimeError("Chain not loaded")

        # Override retriever k at query time
        self.chain.retriever.search_kwargs["k"] = top_k

        result = self.chain.invoke({"query": question})
        answer = result["result"].strip().replace("</s>", "").strip()
        sources = [
            doc.metadata.get("source", "unknown")
            for doc in result.get("source_documents", [])
        ]
        return answer, list(dict.fromkeys(sources))  # deduplicated, order preserved