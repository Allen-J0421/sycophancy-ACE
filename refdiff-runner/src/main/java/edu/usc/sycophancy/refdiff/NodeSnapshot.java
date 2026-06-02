package edu.usc.sycophancy.refdiff;

import java.util.List;

import refdiff.core.cst.CstNode;
import refdiff.core.cst.Location;
import refdiff.core.diff.CstRootHelper;

/**
 * JSON-friendly snapshot of a CST node.
 */
public final class NodeSnapshot {

    public final String kind;
    public final String localName;
    public final String file;
    public final int line;
    public final List<String> path;

    public NodeSnapshot(String kind, String localName, String file, int line, List<String> path) {
        this.kind = kind;
        this.localName = localName;
        this.file = file;
        this.line = line;
        this.path = path;
    }

    public static NodeSnapshot from(CstNode node) {
        if (node == null) {
            return null;
        }
        Location loc = node.getLocation();
        String file = loc != null ? loc.getFile() : "";
        int line = loc != null ? loc.getLine() : 0;
        String kind = node.getType() != null ? node.getType().replace("Declaration", "") : "";
        return new NodeSnapshot(
            kind,
            node.getLocalName(),
            file,
            line,
            CstRootHelper.getNodePath(node));
    }
}
