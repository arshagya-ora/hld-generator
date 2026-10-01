# Create a product profile

A **product profile** is a JSON planning template for one product's HLD. It defines the document sections, their order, and optional writing guidance. It is not a searchable knowledge base. The analyzer extracts project facts from uploaded documents, while the optional retrieval indexes hold reference material.

The public repository does not include product profiles. Create one from material you are allowed to use and keep it private: the default `product_profiles/` directory is ignored by Git.

## 1. Write the JSON

From the repository root, create `product_profiles/ExampleGateway.json` with this minimal profile:

```json
{
  "product": "ExampleGateway",
  "document_type": "HLD",
  "version": "1.0",
  "metadata": {
    "description": "Example gateway design profile",
    "aliases": ["example gateway"]
  },
  "global": {
    "planning_instructions": {
      "special_notes": "Use uploaded project documents for customer-specific facts. Mark missing facts for review."
    }
  },
  "sections": [
    {
      "section_id": "overview",
      "section_number": "1",
      "title": "Solution overview",
      "conditional": false,
      "generation": {
        "dependencies": []
      },
      "rag_queries": ["gateway architecture and interfaces"]
    },
    {
      "section_id": "deployment",
      "section_number": "2",
      "title": "Deployment architecture",
      "conditional": false,
      "generation": {
        "dependencies": ["overview"]
      },
      "rag_queries": ["deployment topology and capacity"]
    }
  ]
}
```

The filename stem must exactly match `product`. Product IDs begin with a letter and use only letters, digits, and underscores. `sections` must contain at least one item. Each item needs a unique `section_id`, a `section_number`, and a `title`. The array order is the final document order. Optional `metadata`, `global`, `past_tocs`, and section guidance can be added as needed. `generation.dependencies` refers to other `section_id` values.

Use product-neutral examples in a shareable template. Do not put customer names, addresses, credentials, unreleased specifications, or copied third-party text in a public repository.

## 2. Validate and make it available

Run from the repository root:

```bash
python -m agents.blueprint.tools.product_profile_loader product_profiles/ExampleGateway.json
```

The API and blueprint agent discover valid `*.json` files in `product_profiles/` automatically. To use another private location, set `PRODUCT_PROFILE_DIR` in `backend/.env` to an absolute path or a path relative to the repository root. Use the same setting for the API, Celery worker, and direct pipeline runs. Restart the API and worker after changing the setting.

If the product selector is empty, check that the file is valid, the filename matches `product`, and the processes can read the configured directory. A newly created generation job stores the selected profile filename; the worker loads the current JSON for that product when it runs.

## 3. Generate a document

Run the app as described in the [README](../README.md#run-locally). Sign in, upload project PDF or DOCX source documents, choose **ExampleGateway**, and create a generation job. Review the resulting HLD against those source documents. The profile controls structure and guidance; it does not establish the truth of product or customer claims.

For a direct pipeline run, use:

```bash
python orchestrator/master_orchestrator.py path/to/project.pdf --product ExampleGateway
```

The retrieval datasets are separate from this JSON. To ground sections in additional permitted product documents or past HLDs, ingest those sources with `python -m tools.ingestion.cli` and select the same product ID. Consult the CLI help for its available ingestion commands.
