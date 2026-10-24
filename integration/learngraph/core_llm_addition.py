"""Add this factory to the team core/llm.py; preserve its existing functions."""


def get_review_service():
    from dotenv import load_dotenv

    from learngraph_review import ReviewService

    load_dotenv()
    return ReviewService()
