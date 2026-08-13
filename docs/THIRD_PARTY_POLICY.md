# Third-party code, model, and dataset policy

CreatorProof treats code, pretrained weights, datasets, papers, and web content as separate artifacts with potentially different rights.

## Promotion rule

A third-party component may enter the commercial runtime only after all of these are recorded:

- exact repository/artifact URL and version or commit;
- code license;
- pretrained-weight/model license;
- dataset/training-data terms where relevant;
- transitive dependency licenses;
- required notices/attribution;
- security and provenance review;
- CreatorProof benchmark report;
- approved runtime role and rollback plan.

## Restricted research material

Non-commercial, nonprofit-only, custom-license, or otherwise unresolved assets remain outside the commercial runtime. They may still inform evaluation questions or research hypotheses where the terms permit that use.

When a useful idea must be recreated without using restricted implementation material, use a clean-room process:

1. One person records only the public paper/spec behavior, inputs, outputs, mathematical description, and benchmark expectations.
2. The implementation task is written from that neutral specification without copying source code, weights, comments, file structure, or tests from the restricted repository.
3. A separate implementation is written from first principles or permissively licensed primitives.
4. Tests compare behavior on independently obtained/licensed data.
5. Keep provenance notes showing what sources informed the specification and what code actually entered the product.

Changing variable names, reorganizing files, translating languages, or lightly rewriting restricted source does not turn copied code into an independent implementation and is not an acceptable license strategy.

