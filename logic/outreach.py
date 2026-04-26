# logic/outreach.py
from crewai import Agent, Task, Crew

def generate_outreach(query, candidate):
    system_prompt = """
    You are Agent Carter, an expert AI networking assistant.
    Generate:
    1. Reasons to reach out
    2. LinkedIn DM
    3. Email subject + body
    """

    agent = Agent(
        role="Networking Assistant",
        goal="Generate outreach that sounds natural",
        llm="gpt-4"
    )

    prompt = f"""
    Query: {query}

    Candidate:
    {candidate}
    """

    task = Task(
        description=system_prompt + "\n" + prompt,
        expected_output="Formatted outreach.",
        agent=agent
    )

    crew = Crew(agents=[agent], tasks=[task])
    return crew.run()
