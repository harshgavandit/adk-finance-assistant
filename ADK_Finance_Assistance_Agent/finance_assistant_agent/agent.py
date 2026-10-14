from google.adk.agents import LlmAgent
from google.adk.tools.agent_tool import AgentTool
from finance_runtime.models import before_agent, before_model, after_model, before_tool, after_tool, create_model, generation_config, on_model_error
from investment_plan_agent.agent import investment_plan_agent


def get_user_personal_finance_details() -> dict:
    """Return a SAMPLE monthly INR finance profile, not authenticated user data."""
    return {
        "data_source": "demo_sample", "currency": "INR", "period": "monthly",
        "salary": 50000,
        "expense": {"EMI_Expense": 25000, "Essentials": 5000,
                    "Entertainment": 5000, "Shopping and Travel": 5000},
        "savings": 10000,
    }


finance_assistance_agent = LlmAgent(
    name="finance_assistance_agent",
    model=create_model(),
    generate_content_config=generation_config(),
    description="Finance assistant for educational explanations, demo budgeting, and investment planning.",
    instruction="""You are a friendly finance education assistant.
    Answer general finance questions and help plan savings goals.
    Use get_user_personal_finance_details for requests to analyze the available profile.
    That profile is DEMO SAMPLE DATA; clearly label it and never claim it is the user's
    actual account. User-provided figures take precedence over the demo profile.
    Delegate current bank rates, stock prices, market/news questions, and anything
    latest/current/today/now/recent to investment_plan_agent, which can search public websites.
    Preserve its source URLs and qualifications in your answer. If live information
    could not be verified, say so; never invent current rates, prices, or citations.
    The available search retrieves snippets, not verified live price feeds. For current
    rates/prices, return the source links and state that exact current values require
    checking those sources. Do not add numeric prices/rates or active schemes from memory.
    Do not put private financial information into search queries.
    Explain calculation assumptions and risks; never promise investment returns.
    If a tool reports an API or rate-limit error, relay that error instead of inventing an answer.
    """,
    tools=[AgentTool(investment_plan_agent), get_user_personal_finance_details],
    before_model_callback=before_model,
    before_agent_callback=before_agent,
    after_model_callback=after_model,
    before_tool_callback=before_tool,
    after_tool_callback=after_tool,
    on_model_error_callback=on_model_error,
)

root_agent = finance_assistance_agent
