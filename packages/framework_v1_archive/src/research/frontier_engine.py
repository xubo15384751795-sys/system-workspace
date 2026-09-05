from __future__ import annotations

from src.research.candidate_signal_factory import CandidateSignalFactory
from src.research.local_state_spaces import LocalStateSpaceRegistry
from src.research.mechanism_composer import MechanismComposer
from src.research.schemas import FrontierResearchBundle
from src.research.structural_mechanism_library import StructuralMechanismLibrary
from src.research.validation_queue import ValidationQueue
from src.research.variable_generator import FrontierVariableGenerator


class FrontierResearchEngine:
    """
    Generate first, constrain after.

    This object intentionally does not use validation status as a pre-filter.
    It emits variables, maps, mechanisms, compositions, and candidate signals,
    then attaches validation queue items and release constraints downstream.
    """

    def __init__(self) -> None:
        self.state_spaces = LocalStateSpaceRegistry()
        self.mechanisms = StructuralMechanismLibrary()
        self.variable_generator = FrontierVariableGenerator(self.state_spaces)
        self.candidate_factory = CandidateSignalFactory()
        self.composer = MechanismComposer(self.mechanisms, self.variable_generator)

    def generate(self) -> FrontierResearchBundle:
        spaces = self.state_spaces.all()
        variables = self.variable_generator.generate_all()
        mechanisms = self.mechanisms.all()
        compositions = self.composer.compose_all()
        candidates = self.candidate_factory.build_all()
        queue = ValidationQueue()
        queue_items = tuple(queue.add(candidate) for candidate in candidates)
        return FrontierResearchBundle(
            local_state_spaces=spaces,
            variables=variables,
            mechanisms=mechanisms,
            compositions=compositions,
            candidate_signals=candidates,
            validation_queue=queue_items,
        )
