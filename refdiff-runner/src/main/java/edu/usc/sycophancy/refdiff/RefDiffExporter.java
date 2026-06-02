package edu.usc.sycophancy.refdiff;

import java.util.ArrayList;
import java.util.Comparator;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.TreeMap;

import refdiff.core.cst.CstNode;
import refdiff.core.cst.Location;
import refdiff.core.diff.CstDiff;
import refdiff.core.diff.Relationship;

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
            record.put("n_refactorings", 0);
            record.put("n_same", 0);
            record.put("n_relationships_total", 0);
            record.put("by_type", Map.of());
            record.put("refactorings", List.of());
            record.put("same_relationships", List.of());
            return record;
        }

        // RefDiff returns relationships in an unordered Set, so impose a stable
        // ordering here to keep the emitted JSON reproducible across runs.
        List<Relationship> sorted = new ArrayList<>(diff.getRelationships());
        sorted.sort(STABLE_ORDER);

        List<Map<String, Object>> refactorings = new ArrayList<>();
        List<Map<String, Object>> sameRelationships = new ArrayList<>();
        // by_type counts refactorings only (excludes SAME); SAME is reported via n_same.
        Map<String, Integer> byType = new TreeMap<>();
        int sameCount = 0;

        for (Relationship rel : sorted) {
            Map<String, Object> relMap = relationshipToMap(rel);
            if (rel.isRefactoring()) {
                byType.merge(rel.getType().name(), 1, Integer::sum);
                refactorings.add(relMap);
            } else {
                sameCount++;
                if (includeSame) {
                    sameRelationships.add(relMap);
                }
            }
        }

        record.put("n_refactorings", refactorings.size());
        record.put("n_same", sameCount);
        record.put("n_relationships_total", sorted.size());
        record.put("by_type", byType);
        record.put("refactorings", refactorings);
        record.put("same_relationships", sameRelationships);
        return record;
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
        map.put("kind", snap.kind);
        map.put("localName", snap.localName);
        map.put("file", snap.file);
        map.put("line", snap.line);
        map.put("path", snap.path);
        return map;
    }
}
