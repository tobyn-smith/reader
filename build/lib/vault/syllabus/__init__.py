"""syllabus intake: pdf in, structured parse out, nothing written to disk.

the pipeline is deterministic. a model may be consulted afterwards to improve
low confidence rows, but never to do the extraction, so this package imports no
model sdk and works with no api keys configured.
"""
