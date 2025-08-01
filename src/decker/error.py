class DeckerError(Exception):
    """
    Custom exception class for Decker-related errors.

    This exception is raised when errors specific to the Decker application occur.
    It extends the built-in Exception class and stores a custom error message.

    Attributes:
        message (str): The error message describing what went wrong.

    Args:
        message (str): A descriptive error message.

    Example:
        >>> raise DeckerError("Configuration file not found")
        DeckerError: Configuration file not found
    """
    def __init__(self, message: str):
        self.message = message
        super().__init__(self.message)
