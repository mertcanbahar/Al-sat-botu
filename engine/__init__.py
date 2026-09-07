# Intentionally empty, and it must stay that way.
#
# `alsatbotu.config` imports `engine.halt` for the HaltPolicy type, while
# `engine.risk` imports `alsatbotu.config` for its tuning. That is acyclic
# only because importing the `engine` package runs no submodule imports. Add
# `from engine.risk import ...` here and `import alsatbotu.config` starts a
# circular import.
