def refine_retrieval_query(query: str) -> str:
    normalized = query.lower()

    if (
        "transformer" in normalized
        and "attention" in normalized
        and "efficien" in normalized
    ):
        return (
            f"{query} "
            "Focus on attention mechanisms that reduce computational cost, "
            "memory usage, KV-cache cost, sparsity, or attention complexity. "
            "Exclude general model compression, distillation, and unrelated "
            "Transformer applications."
        )

    if (
        "transformer" in normalized
        and "long-context" in normalized
        and "efficien" in normalized
    ):
        return (
            f"{query} "
            "Focus on methods that reduce attention computation, memory usage, "
            "or KV-cache cost during long-context Transformer inference. "
            "Prioritize mechanisms directly affecting long-context attention "
            "or inference efficiency."
        )

    return query
