import os
import logging
import re

import torch
import requests
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
GROQ_MODEL       = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
TAVILY_API_KEY   = os.getenv("TAVILY_API_KEY")

# Minimum Pinecone score to trust corpus — below this triggers web fallback
CORPUS_CONFIDENCE_THRESHOLD = 0.60

PROMPT_TEMPLATE = """You are Akasha — the living memory of Teyvat, an omniscient Genshin Impact assistant with the depth of a master theorycafter and the storytelling of a lore scholar.

You have access to peer-reviewed theorycrafting data, exact game stats, and synthesized knowledge across all of Teyvat's history.

ANSWER RULES:
- Be thorough, specific, and structured. Never give one-liners for complex questions.
- Use exact numbers from the context — ER thresholds, EM values, CRIT ratios, multipliers.
- If context is thin on a topic, say: "The Irminsul's records on this are limited." Then share what you do know.
- Never invent stats, story details, or abilities not present in the context.
- Write like an expert who genuinely loves the game — not a generic AI assistant.

FORMAT GUIDE by question type:

For BUILD questions:
**[Character] — [Role] Build**
**How it works:** [brief kit explanation — what makes this character deal damage or provide value]
**Artifacts:** [set name] — [why this set, what the bonus does for this character]
**Main stats:** Sands: [stat] | Goblet: [stat] | Circlet: [stat]
**Substat priority:** [ordered list with thresholds e.g. ER ≥180% → EM → CRIT 1:2]
**Weapons:** BiS: [weapon + why] | F2P: [weapon + why]
**Teams:** [2-3 comps with role explanation]
**Notes:** [rotation tips, constellation breakpoints, common mistakes]

For LORE questions:
Answer in flowing prose. Cover: who they are, their motivations, key relationships, their role in the story, and what makes them memorable. Include specific quest/event references where available.

For MECHANICS questions:
Explain the concept clearly, give the exact formula or interaction, then a practical example showing when/why it matters in actual gameplay.

---
Context from Irminsul records:
{context}

Question: {question}

Akasha:"""

WEB_PROMPT_TEMPLATE = """You are Akasha — the Genshin Impact assistant. The Irminsul's local records didn't have strong coverage for this query, so you retrieved live data from trusted sources.

Trusted source data:
{context}

Answer the question thoroughly using this data. Follow the same format rules:
- Builds: cover artifacts, stats, weapons, teams
- Lore: prose with relationships and story significance  
- Mechanics: formula + practical example

Question: {question}

Akasha (from live sources):"""


def _fetch_wiki_page(character_name: str) -> str:
    """Fetch a character page from wiki.gg as web fallback."""
    slug = character_name.lower().replace(" ", "_")
    urls = [
        f"https://genshin-impact.fandom.com/wiki/{character_name.replace(' ', '_')}",
        f"https://game8.co/games/Genshin-Impact/archives/search?q={character_name}+build",
    ]
    headers = {"User-Agent": "Irminsul-RAG/1.0 (Genshin Impact assistant; educational)"}

    for url in urls:
        try:
            r = requests.get(url, headers=headers, timeout=8)
            if r.status_code == 200:
                text = r.text
                # Strip HTML tags
                text = re.sub(r'<[^>]+>', ' ', text)
                # Strip excessive whitespace
                text = re.sub(r'\s{3,}', '\n\n', text)
                # Return first 4000 chars of meaningful content
                return text[:4000].strip()
        except Exception as e:
            logger.warning(f"Web fallback failed for {url}: {e}")
    return ""


def _extract_subject(query: str) -> str:
    """Best-effort extract character/topic name from query for web fallback."""
    query = query.lower()
    for word in ["build", "lore", "skill", "burst", "talent", "team", "artifact",
                 "who is", "tell me about", "what is", "how does", "explain"]:
        query = query.replace(word, "")
    return query.strip().title()


def route_query(question: str) -> dict:
    """
    Detect query intent and return a Pinecone metadata filter dict.
    Applied per-query, not at startup.
    """
    q = question.lower()

    # Build/optimization intent
    build_keywords = ["build", "weapon", "artifact", "bis", "best in slot",
                      "team", "rotation", "er threshold", "em", "crit",
                      "f2p", "free to play", "comps", "comp"]
    # Lore intent
    lore_keywords = ["lore", "story", "who is", "personality", "history",
                     "background", "quest", "backstory", "relationship"]
    # Stats/numbers intent
    stats_keywords = ["stats", "talent", "constellation", "scaling",
                      "multiplier", "numbers", "c0", "c1", "c2", "c3",
                      "c4", "c5", "c6", "a1", "a4"]
    # Mechanics intent
    mechanics_keywords = ["reaction", "mechanic", "how does", "damage formula",
                          "icd", "internal cooldown", "vaporize", "melt",
                          "swirl", "freeze", "superconduct", "hyperbloom",
                          "burgeon", "quicken", "aggravate", "spread"]

    # Known Genshin character names for character-specific filter
    # This list covers the major characters — not exhaustive
    known_characters = [
        "hu tao", "zhongli", "venti", "kazuha", "raiden", "raiden shogun",
        "bennett", "xingqiu", "yelan", "xiangling", "fischl", "beidou",
        "sucrose", "albedo", "ganyu", "ayaka", "ayato", "itto", "gorou",
        "kokomi", "sara", "yoimiya", "thoma", "shenhe", "yunjin",
        "nahida", "cyno", "tighnari", "collei", "dori", "layla", "faruzan",
        "wanderer", "scaramouche", "alhaitham", "dehya", "mika", "baizhu",
        "kaveh", "nilou", "candace",
        "neuvillette", "furina", "wriothesley", "navia", "charlotte",
        "freminet", "lyney", "lynette", "arlecchino", "clorinde",
        "sigewinne", "emilie", "chevreuse",
        "mualani", "kinich", "kachina", "xilonen", "chasca", "ororon",
        "mavuika", "citlali",
        "lumine", "aether", "paimon",
        "keqing", "diluc", "jean", "qiqi", "mona", "klee", "childe",
        "tartaglia", "eula", "amber", "barbara", "noelle", "razor",
        "lisa", "traveler", "xinyan", "ningguang", "chongyun", "diona",
        "rosaria", "yanfei", "hutao", "sayu", "shogun",
        "yae miko", "yae", "heizou", "shinobu", "tighnari",
        "wanderer", "alhaitham", "baizhu",
    ]

    filter_dict = {}

    # Detect character name in query
    detected_character = None
    for char in known_characters:
        if char in q:
            # Normalize to title case for metadata match
            detected_character = char.title()
            break

    # Determine tier/content_type filter based on intent keywords
    if any(kw in q for kw in build_keywords + mechanics_keywords):
        filter_dict = {"tier": {"$in": ["tcl", "structured"]}}
    elif any(kw in q for kw in lore_keywords):
        filter_dict = {"tier": "wiki"}
    elif any(kw in q for kw in stats_keywords):
        filter_dict = {"content_type": {"$in": ["stats", "ability"]}}
    else:
        filter_dict = {}  # ambiguous — search all tiers

    # Add character filter on top if detected
    if detected_character:
        if filter_dict:
            filter_dict["character"] = detected_character
        else:
            filter_dict = {"character": detected_character}

    logger.info(f"Query routed — filter: {filter_dict}")
    return filter_dict


def _tavily_search(question: str) -> tuple[str, str]:
    """
    Call Tavily search API as web fallback.
    Returns (answer_text, source_url).
    Falls back to empty strings if API key not set or call fails.
    """
    if not TAVILY_API_KEY:
        logger.warning("TAVILY_API_KEY not set — web fallback unavailable")
        return "", ""
    try:
        from tavily import TavilyClient
        client = TavilyClient(api_key=TAVILY_API_KEY)
        # Scope search to Genshin sources for quality
        response = client.search(
            query=f"Genshin Impact {question}",
            search_depth="basic",
            max_results=3,
            include_answer=True,
        )
        answer = response.get("answer", "")
        # Get top source URL
        results = response.get("results", [])
        source_url = results[0]["url"] if results else "web search"
        logger.info(f"Tavily returned answer length: {len(answer)} chars")
        return answer, source_url
    except Exception as e:
        logger.warning(f"Tavily search failed: {e}")
        return "", ""


def _build_groq_llm():
    from langchain_groq import ChatGroq

    if not GROQ_API_KEY:
        raise EnvironmentError("GROQ_API_KEY not set in environment.")

    logger.info(f"Using Groq backend — model: {GROQ_MODEL}")
    return ChatGroq(
        api_key=GROQ_API_KEY,
        model_name=GROQ_MODEL,
        temperature=0.3,
        max_tokens=1500,
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
        max_new_tokens=512,
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
        self.web_chain = None
        self.vectorstore = None
        self.llm = None

    def load(self):
        self.llm = _build_groq_llm() if LLM_BACKEND == "groq" else _build_local_llm()

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
            llm=self.llm,
            chain_type="stuff",
            retriever=self.vectorstore.as_retriever(
                search_kwargs={"k": 8}
            ),
            return_source_documents=True,
            chain_type_kwargs={"prompt": prompt},
        )

        self.ready = True
        logger.info(f"RAG chain ready — backend: {LLM_BACKEND}, model: {GROQ_MODEL}")

    def _corpus_has_coverage(self, question: str) -> tuple[bool, list]:
        """Check if Pinecone has meaningful coverage for this query."""
        # NOTE: not called in query() — kept for reference
        try:
            docs_with_scores = self.vectorstore.similarity_search_with_score(
                question, k=3
            )
            if not docs_with_scores:
                return False, []
            top_score = docs_with_scores[0][1]
            logger.info(f"Top Pinecone score: {top_score:.3f}")
            # Pinecone cosine: higher = more similar
            has_coverage = top_score >= CORPUS_CONFIDENCE_THRESHOLD
            return has_coverage, [doc for doc, _ in docs_with_scores]
        except Exception as e:
            logger.warning(f"Coverage check failed: {e}")
            return True, []  # fail open — try corpus anyway

    def query(self, question: str, top_k: int = 8) -> tuple[str, list[str], str]:
        """
        Returns (answer, sources, retrieval_method)
        retrieval_method: "rag" | "web_fallback" | "guardrail_blocked"
        """
        if not self.ready:
            raise RuntimeError("RAG chain is not loaded.")

        # Step 1: Route query — get metadata filter
        filter_dict = route_query(question)

        # Step 2: Retrieve with scores to check confidence
        try:
            docs_with_scores = self.vectorstore.similarity_search_with_score(
                question, k=top_k, filter=filter_dict if filter_dict else None
            )
        except Exception as e:
            logger.warning(f"Filtered retrieval failed: {e} — retrying without filter")
            docs_with_scores = self.vectorstore.similarity_search_with_score(
                question, k=top_k
            )

        # Step 3: Check confidence
        max_score = docs_with_scores[0][1] if docs_with_scores else 0.0
        logger.info(f"Top Pinecone score: {max_score:.3f} (threshold: {CORPUS_CONFIDENCE_THRESHOLD})")

        if max_score < CORPUS_CONFIDENCE_THRESHOLD:
            logger.info(f"Low confidence ({max_score:.2f}) — falling back to web search")
            tavily_answer, tavily_source = _tavily_search(question)
            if tavily_answer:
                return tavily_answer, [f"web: {tavily_source}"], "web_fallback"
            else:
                logger.warning("Tavily fallback also failed — proceeding with RAG anyway")

        # Step 4: Apply filter to the chain retriever and run RAG
        self.chain.retriever.search_kwargs["k"] = top_k
        if filter_dict:
            self.chain.retriever.search_kwargs["filter"] = filter_dict
        else:
            self.chain.retriever.search_kwargs.pop("filter", None)

        result = self.chain.invoke({"query": question})
        answer = result["result"].strip().replace("</s>", "").strip()
        sources = [
            doc.metadata.get("source", "unknown")
            for doc in result.get("source_documents", [])
        ]
        return answer, list(dict.fromkeys(sources)), "rag"