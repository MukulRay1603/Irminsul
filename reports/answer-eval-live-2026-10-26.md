{
  "items": 114,
  "scored": 114,
  "needs_llm": 0,
  "pass_rate": 0.974,
  "by_category": {
    "beginner": "4/4",
    "build": "5/6",
    "gacha": "4/4",
    "injection": "3/3",
    "leak_probe": "5/5",
    "mechanic": "5/6",
    "offtopic": "3/3",
    "passive": "30/31",
    "stat": "49/49",
    "upcoming": "3/3"
  },
  "routes": {
    "announced": 3,
    "exact": 77,
    "rag": 23,
    "refuse_injection": 3,
    "refuse_leak": 5,
    "refuse_offtopic": 3
  },
  "failures": [
    {
      "id": "man-stellar-def",
      "category": "mechanic",
      "status": "fail",
      "route": "rag",
      "problems": [
        "gold doc not cited"
      ],
      "latency_ms": 923.1
    },
    {
      "id": "viewer-skirk-exaiphanes",
      "category": "passive",
      "status": "fail",
      "route": "rag",
      "problems": [
        "missing one of ['CRIT Rate']"
      ],
      "latency_ms": 2307.1
    },
    {
      "id": "viewer-skirk-4th-slot",
      "category": "build",
      "status": "fail",
      "route": "rag",
      "problems": [
        "missing one of ['Cryo']"
      ],
      "latency_ms": 1099.1
    }
  ]
}