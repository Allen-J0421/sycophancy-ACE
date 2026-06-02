package edu.usc.sycophancy.refdiff;

import java.io.File;
import java.io.FileOutputStream;
import java.io.OutputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.List;
import java.util.Map;

import org.eclipse.jgit.lib.ObjectId;
import org.eclipse.jgit.lib.Repository;
import org.eclipse.jgit.revwalk.RevCommit;
import org.eclipse.jgit.revwalk.RevWalk;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.ObjectWriter;
import refdiff.core.diff.CstComparator;
import refdiff.core.diff.CstDiff;
import refdiff.core.diff.Relationship;
import refdiff.core.io.FilePathFilter;
import refdiff.core.io.GitHelper;
import refdiff.core.io.SourceFileSet;
import refdiff.core.util.PairBeforeAfter;
import refdiff.parsers.java.JavaPlugin;

/**
 * CLI wrapper around RefDiff for local git repositories.
 */
public final class RefDiffRunner {

    private RefDiffRunner() {}

    public static void main(String[] args) {
        CliOptions opts;
        try {
            opts = CliOptions.parse(args);
        } catch (IllegalArgumentException e) {
            System.err.println(e.getMessage());
            printUsageAndExit(1);
            return;
        }

        File repoPath = new File(opts.repo).getAbsoluteFile();
        File gitDir;
        try {
            gitDir = resolveGitDir(repoPath);
        } catch (GitDirException e) {
            System.err.println(e.getMessage());
            System.exit(2);
            return;
        }

        String parentSha = "";
        String resolvedCommitSha = opts.commit;
        long startMs = System.currentTimeMillis();
        Map<String, Object> record;
        int exitCode = 0;

        try {
            File tempDir = new File(".refdiff-tmp").getAbsoluteFile();
            if (!tempDir.exists() && !tempDir.mkdirs()) {
                throw new RuntimeException("Failed to create temp directory: " + tempDir);
            }

            CollectingMatcherMonitor monitor = new CollectingMatcherMonitor();
            JavaPlugin plugin = new JavaPlugin(tempDir);
            FilePathFilter fileFilter = plugin.getAllowedFilesFilter();
            CstDiff diff;
            long durationMs;
            try (Repository repository = GitHelper.openRepository(gitDir)) {
                CommitInfo info = resolveCommit(repository, opts.commit);
                resolvedCommitSha = info.sha;
                parentSha = info.parentSha != null ? info.parentSha : "";

                PairBeforeAfter<SourceFileSet> sources =
                    GitHelper.getSourcesBeforeAndAfterCommit(repository, opts.commit, fileFilter);
                CstComparator comparator = new CstComparator(plugin);
                long compareStartMs = System.currentTimeMillis();
                diff = comparator.compare(sources.getBefore(), sources.getAfter(), monitor);
                durationMs = System.currentTimeMillis() - compareStartMs;
            }

            if (opts.matcherLog != null) {
                File matcherFile = new File(opts.matcherLog);
                matcherFile.getParentFile().mkdirs();
                Files.write(matcherFile.toPath(), monitor.getLines(), StandardCharsets.UTF_8);
            }

            record = RefDiffExporter.buildRecord(
                repoPath.getPath(),
                resolvedCommitSha,
                parentSha,
                diff,
                opts.includeSame,
                monitor.getLines(),
                durationMs,
                true,
                "");

            if (!opts.quiet) {
                printHumanSummary(repoPath, gitDir, resolvedCommitSha, diff);
            }

            writeOutput(record, opts);

        } catch (Exception e) {
            long durationMs = System.currentTimeMillis() - startMs;
            exitCode = 1;
            record = RefDiffExporter.buildRecord(
                repoPath.getPath(),
                resolvedCommitSha,
                parentSha,
                null,
                opts.includeSame,
                List.of(),
                durationMs,
                false,
                e.getMessage() != null ? e.getMessage() : e.getClass().getSimpleName());

            if (!opts.quiet) {
                System.err.println("RefDiff failed: " + e.getMessage());
            }

            try {
                writeOutput(record, opts);
            } catch (Exception writeErr) {
                System.err.println("Failed to write output: " + writeErr.getMessage());
                exitCode = 2;
            }
        }

        System.exit(exitCode);
    }

    private static void writeOutput(Map<String, Object> record, CliOptions opts) throws Exception {
        ObjectMapper mapper = new ObjectMapper();
        ObjectWriter writer = opts.pretty
            ? mapper.writerWithDefaultPrettyPrinter()
            : mapper.writer();
        if (opts.out != null) {
            try (OutputStream os = new FileOutputStream(opts.out)) {
                writer.writeValue(os, record);
            }
        } else {
            writer.writeValue(System.out, record);
        }
    }

    private static void printHumanSummary(File repoPath, File gitDir, String commitSha, CstDiff diff) {
        System.out.println("Repository: " + repoPath);
        System.out.println("Git dir:    " + gitDir);
        System.out.println("Commit:     " + commitSha);
        System.out.println();
        int count = 0;
        for (Relationship rel : diff.getRefactoringRelationships()) {
            System.out.println(rel.getStandardDescription());
            count++;
        }
        if (count == 0) {
            System.out.println("(no refactorings detected)");
        }
    }

    static CommitInfo resolveCommit(Repository repository, String commitRef) throws Exception {
        try (RevWalk rw = new RevWalk(repository)) {
            ObjectId objectId = repository.resolve(commitRef);
            if (objectId == null) {
                throw new IllegalArgumentException("Unknown commit: " + commitRef);
            }
            RevCommit commit = rw.parseCommit(objectId);
            String sha = commit.getId().getName();
            String parentSha = null;
            if (commit.getParentCount() >= 1) {
                parentSha = commit.getParent(0).getName();
            }
            return new CommitInfo(sha, parentSha);
        }
    }

    static final class CommitInfo {
        final String sha;
        final String parentSha;

        CommitInfo(String sha, String parentSha) {
            this.sha = sha;
            this.parentSha = parentSha;
        }
    }

    static File resolveGitDir(File path) throws GitDirException {
        File dotGit = new File(path, ".git");
        if (dotGit.isDirectory()) {
            return dotGit.getAbsoluteFile();
        }
        if (".git".equals(path.getName()) && path.isDirectory()) {
            return path.getAbsoluteFile();
        }
        if (path.isDirectory() && path.getName().endsWith(".git")) {
            return path.getAbsoluteFile();
        }
        throw new GitDirException("Not a git repository: " + path);
    }

    static final class GitDirException extends Exception {
        GitDirException(String message) {
            super(message);
        }
    }

    private static void printUsageAndExit(int code) {
        System.err.println("Usage: refdiff-runner --repo <path> --commit <sha> [--out <file.json>]");
        System.err.println("       [--include-same] [--matcher-log <file>] [--pretty] [--quiet]");
        System.exit(code);
    }

    static final class CliOptions {
        final String repo;
        final String commit;
        final String out;
        final String matcherLog;
        final boolean includeSame;
        final boolean pretty;
        final boolean quiet;

        CliOptions(
                String repo,
                String commit,
                String out,
                String matcherLog,
                boolean includeSame,
                boolean pretty,
                boolean quiet) {
            this.repo = repo;
            this.commit = commit;
            this.out = out;
            this.matcherLog = matcherLog;
            this.includeSame = includeSame;
            this.pretty = pretty;
            this.quiet = quiet;
        }

        static CliOptions parse(String[] args) {
            String repo = null;
            String commit = null;
            String out = null;
            String matcherLog = null;
            boolean includeSame = false;
            boolean pretty = false;
            boolean quiet = false;

            for (int i = 0; i < args.length; i++) {
                String arg = args[i];
                switch (arg) {
                    case "--repo":
                        repo = requireValue(args, ++i, "--repo");
                        break;
                    case "--commit":
                        commit = requireValue(args, ++i, "--commit");
                        break;
                    case "--out":
                        out = requireValue(args, ++i, "--out");
                        break;
                    case "--matcher-log":
                        matcherLog = requireValue(args, ++i, "--matcher-log");
                        break;
                    case "--include-same":
                        includeSame = true;
                        break;
                    case "--pretty":
                        pretty = true;
                        break;
                    case "--quiet":
                        quiet = true;
                        break;
                    default:
                        throw new IllegalArgumentException("Unknown argument: " + arg);
                }
            }

            if (repo == null || commit == null) {
                throw new IllegalArgumentException("--repo and --commit are required");
            }
            return new CliOptions(repo, commit, out, matcherLog, includeSame, pretty, quiet);
        }

        private static String requireValue(String[] args, int index, String flag) {
            if (index >= args.length) {
                throw new IllegalArgumentException("Missing value for " + flag);
            }
            return args[index];
        }
    }
}
