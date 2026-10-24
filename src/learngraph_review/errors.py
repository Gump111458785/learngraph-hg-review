class ReviewError(ValueError):
    """A review failed; callers must not interpret this as approval."""


class ExtractionError(ReviewError):
    """The supplied file cannot be extracted reliably."""
