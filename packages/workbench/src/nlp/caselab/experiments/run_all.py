"""Run all CaseLab emergence experiments in isolation.

READS: CaseLab vault via adapter
WRITES: Data/nlp/caselab_experiments/ ONLY
DOES NOT modify System code, data, or outputs.

Usage:
    cd /Users/a1/Verity
    python3 -m nlp.caselab.experiments.run_all
"""
from __future__ import annotations

from pathlib import Path


from nlp.caselab.adapter import CaseLabAdapter
from nlp.caselab.experiments import mechanism_graph, entity_graph, text_emergence

CASELAB_ROOT = Path("/Users/a1/Paper")


def main():
    print("=== CaseLab Emergence Experiments ===")
    print(f"Vault: {CASELAB_ROOT}")
    print("Output: Data/nlp/caselab_experiments/")
    print()

    # Load data
    adapter = CaseLabAdapter(CASELAB_ROOT)
    cases_raw = adapter.load_cases()
    entities_raw = adapter.load_entities()

    # Convert to dicts for experiment modules
    cases = []
    for c in cases_raw:
        cases.append({
            "case_id": c.case_id,
            "case_name": c.case_name,
            "case_type": c.case_type,
            "mechanisms": c.mechanisms,
            "tags": c.tags,
            "narrative_summary": c.narrative_summary,
            "risk_migration": c.risk_migration,
            "feedback_loop": c.feedback_loop,
            "related_entities": c.related_entities,
            "variable_vector": c.variable_vector,
        })

    entities = []
    for e in entities_raw:
        entities.append({
            "entity_id": e.entity_id,
            "entity_name": e.entity_name,
            "entity_type": e.entity_type,
            "related_mechanisms": e.related_mechanisms,
            "related_cases": e.related_cases,
            "dna_text": e.dna_text,
            "inertia_text": e.inertia_text,
        })

    print(f"Loaded: {len(cases)} cases, {len(entities)} entities")
    print()

    # Experiment 1: Mechanism co-occurrence graph
    print("[1/3] Mechanism co-occurrence graph...")
    mech_result = mechanism_graph.run(cases)
    print(f"  Mechanisms: {mech_result['total_mechanisms']}")
    print(f"  Clusters found: {len(mech_result['clusters'])}")
    for c in mech_result["clusters"][:5]:
        mechs = ", ".join(c["mechanisms"][:4])
        print(f"    {c['label']}: [{mechs}] (density={c['density']:.3f})")
    if mech_result["bridge_mechanisms"]:
        print("  Bridge mechanisms:")
        for b in mech_result["bridge_mechanisms"][:3]:
            print(f"    {b['mechanism']}: bridges {b['bridges_clusters']} clusters")
    print()

    # Experiment 2: Entity-mechanism graph
    print("[2/3] Entity-mechanism graph...")
    ent_result = entity_graph.run(entities, cases)
    print(f"  Entities: {ent_result['total_entities']}")
    print(f"  Qualified (≥2 mechanisms): {ent_result['qualified_entities']}")
    print(f"  Emergent roles found: {len(ent_result['emergent_roles'])}")
    for r in ent_result["emergent_roles"][:5]:
        ents = ", ".join(r["entities"][:3])
        print(f"    {r['role']}: [{ents}] (size={r['size']})")
    if ent_result["bridge_entities"]:
        print("  Bridge entities:")
        for b in ent_result["bridge_entities"][:3]:
            print(f"    {b['entity_id']}: bridges {b['bridges_clusters']} roles → {b['cluster_roles']}")
    print()

    # Experiment 3: Text emergence
    print("[3/3] Text emergence...")
    text_result = text_emergence.run(cases)
    print(f"  Concepts found: {text_result['total_concepts']}")
    print(f"  Emergent dimensions: {len(text_result['emergent_dimensions'])}")
    for d in text_result["emergent_dimensions"][:5]:
        top = d["top_cases"][0]["case_id"] if d["top_cases"] else "N/A"
        print(f'    {d["dimension_id"]} ({d["name"]}): {len(d["concepts"])} concepts, density={d["density"]:.2f}, top={top}')
    print()

    print("=== Done ===")
    print("All results in Data/nlp/caselab_experiments/")
    print("  mechanism_graph.json")
    print("  mechanism_cooccurrence.csv")
    print("  entity_graph.json")
    print("  text_emergence.json")


if __name__ == "__main__":
    main()
