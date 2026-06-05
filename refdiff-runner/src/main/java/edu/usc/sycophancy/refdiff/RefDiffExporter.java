package edu.usc.sycophancy.refdiff;

import java.util.ArrayList;
import java.util.Comparator;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import refdiff.core.cst.CstNode;
import refdiff.core.cst.Location;
import refdiff.core.diff.CstDiff;
import refdiff.core.diff.Relationship;
import refdiff.core.diff.RelationshipType;

/**
 * Builds a JSON-serializable map from a {@link CstDiff} and run metadata.
 */
public final class RefDiffExporter {

    private RefDiffExporter() {}

    public static Map<String, Object> buildRecord(
            String repoPath,
            String commitSha,
            String parentSha,
            CstDiff diff,
            boolean includeSame,
            List<String> matcherDiscarded,
            long durationMs,
            boolean refdiffOk,
            String errorMessage) {

        Map<String, Object> record = new LinkedHashMap<>();
        record.put("repo_path", repoPath);
        record.put("commit_sha", commitSha);
        record.put("parent_sha", parentSha != null ? parentSha : "");
        record.put("refdiff_ok", refdiffOk);
        record.put("error_message", errorMessage != null ? errorMessage : "");
        record.put("duration_ms", durationMs);
        record.put("matcher_discarded", matcherDiscarded != null ? matcherDiscarded : List.of());

        if (!refdiffOk || diff == null) {
            record.put("n_same", 0);
            record.put("n_matching", 0);
            record.put("n_non_matching", 0);
            record.put("n_relationships_total", 0);
            record.put("nodes_before", List.of());
            record.put("nodes_after", List.of());
            record.put("matching_relationships", List.of());
            record.put("non_matching_relationships", List.of());
            record.put("node_relationships", Map.of());
            return record;
        }

        List<Map<String, Object>> nodesBefore = new ArrayList<>();
        diff.getBefore().forEachNode((n, depth) -> nodesBefore.add(nodeOrNull(n)));
        List<Map<String, Object>> nodesAfter = new ArrayList<>();
        diff.getAfter().forEachNode((n, depth) -> nodesAfter.add(nodeOrNull(n)));
        record.put("nodes_before", nodesBefore);
        record.put("nodes_after", nodesAfter);

        // RefDiff returns relationships in an unordered Set, so impose a stable
        // ordering here to keep the emitted JSON reproducible across runs.
        List<Relationship> sorted = new ArrayList<>(diff.getRelationships());
        sorted.sort(STABLE_ORDER);

        List<Map<String, Object>> matchingRelationships = new ArrayList<>();
        List<Map<String, Object>> nonMatchingRelationships = new ArrayList<>();
        int sameCount = 0;
        int matchingCount = 0;
        int nonMatchingCount = 0;

        for (Relationship rel : sorted) {
            boolean isMatching = rel.getType().isMatching();
            if (isMatching) {
                matchingCount++;
            } else {
                nonMatchingCount++;
            }

            Map<String, Object> relMap = relationshipToMap(rel);
            if (isMatching) {
                if (rel.getType() == RelationshipType.SAME) {
                    sameCount++;
                    if (includeSame) {
                        matchingRelationships.add(relMap);
                    }
                } else {
                    matchingRelationships.add(relMap);
                }
            } else {
                nonMatchingRelationships.add(relMap);
            }
        }

        record.put("n_same", sameCount);
        record.put("n_matching", matchingCount);
        record.put("n_non_matching", nonMatchingCount);
        record.put("n_relationships_total", sorted.size());
        record.put("matching_relationships", matchingRelationships);
        record.put("non_matching_relationships", nonMatchingRelationships);
        record.put("node_relationships", buildNodeRelationships(nodesBefore, nodesAfter, sorted));
        return record;
    }

    private static Map<String, Object> buildNodeRelationships(
            List<Map<String, Object>> nodesBefore,
            List<Map<String, Object>> nodesAfter,
            List<Relationship> relationships) {
        Map<String, Object> nodeRelationships = new LinkedHashMap<>();

        for (Map<String, Object> node : nodesBefore) {
            if (node == null) {
                continue;
            }
            String key = nodeKeyForRole("before", node);
            Map<String, Object> entry = new LinkedHashMap<>();
            entry.put("node", node);
            entry.put("relationships", new ArrayList<>());
            nodeRelationships.put(key, entry);
        }
        for (Map<String, Object> node : nodesAfter) {
            if (node == null) {
                continue;
            }
            String key = nodeKeyForRole("after", node);
            Map<String, Object> entry = new LinkedHashMap<>();
            entry.put("node", node);
            entry.put("relationships", new ArrayList<>());
            nodeRelationships.put(key, entry);
        }

        for (Relationship rel : relationships) {
            CstNode before = rel.getNodeBefore();
            CstNode after = rel.getNodeAfter();
            if (before == null || after == null) {
                continue;
            }
            String beforeKey = nodeKeyForRole("before", before.getId());
            String afterKey = nodeKeyForRole("after", after.getId());

            @SuppressWarnings("unchecked")
            List<Map<String, Object>> beforeRels =
                (List<Map<String, Object>>) getOrCreateEntry(nodeRelationships, beforeKey, before).get("relationships");
            beforeRels.add(relationshipRef(rel, "before", afterKey));

            @SuppressWarnings("unchecked")
            List<Map<String, Object>> afterRels =
                (List<Map<String, Object>>) getOrCreateEntry(nodeRelationships, afterKey, after).get("relationships");
            afterRels.add(relationshipRef(rel, "after", beforeKey));
        }

        return nodeRelationships;
    }

    @SuppressWarnings("unchecked")
    private static Map<String, Object> getOrCreateEntry(
            Map<String, Object> nodeRelationships, String key, CstNode node) {
        Map<String, Object> entry = (Map<String, Object>) nodeRelationships.get(key);
        if (entry != null) {
            return entry;
        }
        entry = new LinkedHashMap<>();
        entry.put("node", nodeOrNull(node));
        entry.put("relationships", new ArrayList<>());
        nodeRelationships.put(key, entry);
        return entry;
    }

    private static Map<String, Object> relationshipRef(
            Relationship rel, String role, String counterpartKey) {
        Map<String, Object> ref = new LinkedHashMap<>();
        ref.put("type", rel.getType().name());
        ref.put("is_matching", rel.getType().isMatching());
        ref.put("role", role);
        ref.put("counterpart_key", counterpartKey);
        ref.put("similarity", rel.getSimilarity());
        return ref;
    }

    private static String nodeKeyForRole(String role, Map<String, Object> node) {
        Object idObj = node.get("id");
        int id = idObj instanceof Number ? ((Number) idObj).intValue() : 0;
        return nodeKeyForRole(role, id);
    }

    private static String nodeKeyForRole(String role, int id) {
        return role + ":" + id;
    }

    /**
     * Stable, content-based ordering for relationships so the JSON record is reproducible.
     * Orders by relationship type, then the before/after node location+name, then similarity.
     */
    private static final Comparator<Relationship> STABLE_ORDER = Comparator
        .comparing((Relationship r) -> r.getType().name())
        .thenComparing(r -> nodeKey(r.getNodeBefore()))
        .thenComparing(r -> nodeKey(r.getNodeAfter()))
        .thenComparing(r -> r.getSimilarity() == null ? -1.0 : r.getSimilarity());

    private static String nodeKey(CstNode node) {
        if (node == null) {
            return "";
        }
        Location loc = node.getLocation();
        String file = loc != null ? loc.getFile() : "";
        int line = loc != null ? loc.getLine() : 0;
        String localName = node.getLocalName() != null ? node.getLocalName() : "";
        return file + ":" + line + ":" + localName;
    }

    /**
     * Maps a single relationship to its JSON form.
     *
     * <p>Note: {@code similarity} is {@code null} for relationships matched by id/name/signature
     * (e.g. RENAME, MOVE, CHANGE_SIGNATURE, SAME). RefDiff only attaches a score to
     * EXTRACT, EXTRACT_MOVE and INLINE (set in {@code matchExtract}/{@code matchInline}).
     * When {@code similarity} is null, {@code description_with_score} is identical to
     * {@code description_standard}.
     */
    private static Map<String, Object> relationshipToMap(Relationship rel) {
        Map<String, Object> map = new LinkedHashMap<>();
        map.put("type", rel.getType().name());
        map.put("is_matching", rel.getType().isMatching());
        map.put("similarity", rel.getSimilarity());
        map.put("description_standard", rel.getStandardDescription());
        map.put("description_with_score", descriptionWithScore(rel));
        map.put("before", nodeOrNull(rel.getNodeBefore()));
        map.put("after", nodeOrNull(rel.getNodeAfter()));
        return map;
    }

    private static String descriptionWithScore(Relationship rel) {
        String standard = rel.getStandardDescription();
        if (rel.getSimilarity() == null) {
            return standard;
        }
        String prefix = rel.getType().name() + "\t";
        String rest = standard.startsWith(prefix) ? standard.substring(prefix.length()) : standard;
        return rel.getType().name()
            + " (score="
            + String.format("%.3f", rel.getSimilarity())
            + ")\t"
            + rest;
    }

    private static Map<String, Object> nodeOrNull(CstNode node) {
        NodeSnapshot snap = NodeSnapshot.from(node);
        if (snap == null) {
            return null;
        }
        Map<String, Object> map = new LinkedHashMap<>();
        map.put("id", snap.id);
        map.put("kind", snap.kind);
        map.put("localName", snap.localName);
        map.put("file", snap.file);
        map.put("line", snap.line);
        map.put("path", snap.path);
        return map;
    }
}
