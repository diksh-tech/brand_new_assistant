# client.py
import os
import json
import logging
import asyncio
import re
from typing import List, Dict, Any
from datetime import datetime, timedelta

from dotenv import load_dotenv
from openai import AzureOpenAI
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

from tool_registry import TOOLS

# Load environment variables
load_dotenv()

MCP_SERVER_URL = os.getenv("MCP_SERVER_URL", "http://127.0.0.1:8000").rstrip("/")

# Azure OpenAI configuration
AZURE_OPENAI_KEY = os.getenv("AZURE_OPENAI_KEY")
AZURE_OPENAI_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT")
AZURE_OPENAI_DEPLOYMENT = os.getenv("AZURE_OPENAI_DEPLOYMENT_NAME", "gpt-4o")
AZURE_API_VERSION = os.getenv("AZURE_API_VERSION", "2024-12-01-preview")

if not AZURE_OPENAI_KEY:
    raise RuntimeError("❌ AZURE_OPENAI_KEY not set in environment")

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger("FlightOps.MCPClient")

# Initialize Azure OpenAI client
client_azure = AzureOpenAI(
    api_key=AZURE_OPENAI_KEY,
    api_version=AZURE_API_VERSION,
    azure_endpoint=AZURE_OPENAI_ENDPOINT
)

# ---------------------------------------------------------------------
#  SYSTEM PROMPTS
# ---------------------------------------------------------------------
def _build_tool_prompt() -> str:
    """Convert TOOLS dict into compact text to feed the LLM."""
    lines = []
    for name, meta in TOOLS.items():
        arg_str = ", ".join(meta["args"])
        lines.append(f"- {name}({arg_str}): {meta['desc']}")
    return "\n".join(lines)


SYSTEM_PROMPT_PLAN = f"""
You are an assistant that converts user questions into MCP tool calls.

Available tools:
{_build_tool_prompt()}

### TIME CONVERSION RULES:
1. **ALWAYS convert UTC times to local time (IST)** when showing to users
2. Use `convert_utc_to_local_time` for:
   - Flight departure/arrival times
   - Scheduled times  
   - Any UTC timestamp from flight data
   - When user asks "what time is it?" or "current time"

3. **Example usage:**
   - Input: "2024-06-23 13:25" (UTC)
   - Output: Shows both UTC and IST (13:25 UTC → 18:55 IST)

4. **Never show only UTC** - always convert to local time

### MULTIPLE DOCUMENTS HANDLING:

When user asks for flight information (like delay info, basic info, etc.):

1. **Use `multiple=True` parameter** when there might be multiple documents
2. **For flight-specific queries**, always include `multiple=True` to get all documents
3. **The system will automatically handle route selection** if multiple documents are found

### Tool selection logic

1. **Use `run_aggregated_query`** when the user asks for:
   - counts, numbers, totals, sums, averages, minimums, or maximums
   - examples: "how many flights", "number of passengers", "average delay", "max flight time", "total fuel"
   - In such cases:
     - set `"query_type"` to one of ["count", "sum", "average", "min", "max"]
     - set `"field"` to the appropriate MongoDB path (e.g. "flightLegState.pax.passengerCount.count")
     - if the user gives a condition (e.g. "where delay > 30"), include it as `"filter_json"`
     - optionally include `"start_date"` and `"end_date"` for time ranges

     Example:
     {{
       "plan": [
         {{
           "tool": "run_aggregated_query",
           "arguments": {{
             "query_type": "count",
             "field": "flightLegState.pax.passengerCount.count",
             "filter_json": "{{ 'flightLegState.pax.passengerCount.count': {{ '$gt': 100 }} }}"
           }}
         }}
       ]
     }}

2. **Use `raw_mongodb_query`** for:
   - retrieving lists of flights, filtered data, or detailed fields
   - when the question asks to "show", "list", "find", or "get" specific flight data
   - supports `"projection"` to reduce payload (LLM decides what to include)
   - use `"multiple": true` to get all matching documents

     Example:
     {{
       "plan": [
         {{
           "tool": "raw_mongodb_query",
           "arguments": {{
             "query_json": "{{ 'flightLegState.startStation': 'DEL', 'flightLegState.endStation': 'BOM' }}",
             "projection": "{{ 'flightLegState.flightNumber': 1, 'flightLegState.startStation': 1, 'flightLegState.endStation': 1, '_id': 0 }}",
             "limit": 10,
             "multiple": true
           }}
         }}
       ]
     }}

3. **Use existing tools** (like get_flight_basic_info, get_delay_summary, etc.) for single-flight queries with `multiple=true` when flight number and date are specified.

---

### Schema summary (for projection guidance)

Flight documents contain(Schema):
    'carrier': 'flightLegState.carrier',
    'date_of_origin': 'flightLegState.dateOfOrigin',
    'flight_number': 'flightLegState.flightNumber',
    'suffix': 'flightLegState.suffix',
    'sequence_number': 'flightLegState.seqNumber',
    'origin': 'flightLegState.startStation',
    'destination': 'flightLegState.endStation',
    'scheduled_departure': 'flightLegState.scheduledStartTime',
    'scheduled_arrival': 'flightLegState.scheduledEndTime',
    'end_terminal': 'flightLegState.endTerminal',
    'operational_status': 'flightLegState.operationalStatus',
    'flight_status': 'flightLegState.flightStatus',
    'start_country': 'flightLegState.startCountry',
    'end_country': 'flightLegState.endCountry',
    'aircraft_registration': 'flightLegState.equipment.aircraftRegistration',
    'aircraft_type': 'flightLegState.equipment.assignedAircraftTypeIATA',
    'start_gate': 'flightLegState.startGate',
    'end_gate': 'flightLegState.endGate',
    'start_terminal': 'flightLegState.startTerminal',
    'delay_total': 'flightLegState.delays.total',
    'flight_type': 'flightLegState.flightType',
    'operations': 'flightLegState.operation',
    'estimated_times': 'flightLegState.operation.estimatedTimes',
    'off_block_time': 'flightLegState.operation.estimatedTimes.offBlock',
    'in_block_time': 'flightLegState.operation.estimatedTimes.inBlock',
    'takeoff_time': 'flightLegState.operation.estimatedTimes.takeoffTime',
    'landing_time': 'flightLegState.operation.estimatedTimes.landingTime',
    'actual_times': 'flightLegState.operation.actualTimes',
    'actual_off_block_time': 'flightLegState.operation.actualTimes.offBlock',
    'actual_in_block_time': 'flightLegState.operation.actualTimes.inBlock',
    'actual_takeoff_time': 'flightLegState.operation.actualTimes.takeoffTime',
    'actual_landing_time': 'flightLegState.operation.actualTimes.landingTime',
    'door_close_time': 'flightLegState.operation.estimatedTimes.doorClose',
    'fuel':'flightLegState.operation.fuel',
    'fuel_off_block':'flightLegState.operation.fuel.offBlock',
    'fuel_takeoff':'flightLegState.operation.fuel.takeoff',
    'fuel_landing':'flightLegState.operation.fuel.landing',
    'fuel_in_block':'flightLegState.operation.fuel.inBlock',
    'autoland':'flightLegState.operation.autoland',
    'flight_plan':'flightLegState.operation.flightPlan',
    'estimated_Elapsed_time':'flightLegState.operation.flightPlan.estimatedElapsedTime',
    'actual_Takeoff_time':'flightLegState.operation.flightPlan.acTakeoffWeight',
    'flight_plan_takeoff_fuel':'flightLegState.operation.flightPlan.takeoffFuel',
    'flight_plan_landing_fuel':'flightLegState.operation.flightPlan.landingFuel',
    'flight_plan_hold_fuel':'flightLegState.operation.flightPlan.holdFuel',
    'flight_plan_hold_time':'flightLegState.operation.flightPlan.holdTime',
    'flight_plan_route_distance':'flightLegState.operation.flightPlan.routeDistance',

---

### Projection rules for `raw_mongodb_query`
- Only include fields relevant to the question.
- Always exclude "_id".
- Examples:
  - "passenger" → include flightNumber, pax.passengerCount
  - "delay" or "reason" → include flightNumber, delays.total, delays.delay.reason
  - "aircraft" or "tail" → include equipment.aircraftRegistration, aircraft.type
  - "station" or "sector" → include startStation, endStation, terminals
  - "crew" → include crewConnections.crew.givenName, position
  - "timing / departure / arrival / dep / arr" → include scheduledStartTime, scheduledEndTime, operation.actualTimes
  - "fuel" → include operation.fuel
  - "OTP" or "on-time" → include isOTPAchieved, flightStatus

---

### General rules
1. Always return valid JSON with a top-level "plan" key.
2. Use the correct tool type based on query intent.
3. Never invent field names — use schema fields only.
4. Never return "_id" in projections.
5. For numerical summaries → use run_aggregated_query.
6. For filtered listings → use raw_mongodb_query with multiple=true.
7. For time conversions → use convert_utc_to_local_time
8. For flight-specific queries → use multiple=true to handle multiple documents
"""


SYSTEM_PROMPT_SUMMARIZE = """
You are an assistant that summarizes tool outputs into a concise, readable answer.
When summarizing time conversions, clearly mention the UTC time, the +5:30 hour offset applied,
and the resulting local (IST) time. Focus on clarity and readability.
Be factual, short, and helpful.
"""

# ---------------------------------------------------------------------
#  FLIGHTOPS MCP CLIENT CLASS
# ---------------------------------------------------------------------
class FlightOpsMCPClient:
    def __init__(self, base_url: str = None):
        self.base_url = (base_url or MCP_SERVER_URL).rstrip("/")
        self.session: ClientSession = None
        self._client_context = None

    # -------------------- CONNECTION HANDLERS -------------------------
    async def connect(self):
        try:
            logger.info(f"Connecting to MCP server at {self.base_url}")
            self._client_context = streamablehttp_client(self.base_url)
            read_stream, write_stream, _ = await self._client_context.__aenter__()
            self.session = ClientSession(read_stream, write_stream)
            await self.session.__aenter__()
            await self.session.initialize()
            logger.info("✅ Connected to MCP server successfully")
        except Exception as e:
            logger.error(f"Failed to connect to MCP server: {e}")
            raise

    async def disconnect(self):
        try:
            if self.session:
                await self.session.__aexit__(None, None, None)
            if self._client_context:
                await self._client_context.__aexit__(None, None, None)
            logger.info("Disconnected from MCP server")
        except Exception as e:
            logger.error(f"Error during disconnect: {e}")

    # -------------------- AZURE OPENAI WRAPPER -------------------------
    def _call_azure_openai(self, messages: list, temperature: float = 0.2, max_tokens: int = 2048) -> dict:
        try:
            completion = client_azure.chat.completions.create(
                model=AZURE_OPENAI_DEPLOYMENT,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
            )
            usage_obj = getattr(completion, "usage", None)
            usage = None
            if usage_obj is not None:
                usage = {
                    "prompt_tokens": getattr(usage_obj, "prompt_tokens", 0) or 0,
                    "completion_tokens": getattr(usage_obj, "completion_tokens", 0) or 0,
                    "total_tokens": getattr(usage_obj, "total_tokens", 0) or 0,
                }
            return {
                "content": completion.choices[0].message.content,
                "usage": usage
            }
        except Exception as e:
            logger.error(f"Azure OpenAI API error: {e}")
            return {"content": json.dumps({"error": str(e)}), "usage": None}

    # -------------------- MCP TOOL CALLS -------------------------
    async def list_tools(self) -> dict:
        try:
            if not self.session:
                await self.connect()
            tools_list = await self.session.list_tools()
            tools_dict = {tool.name: {"description": tool.description, "inputSchema": tool.inputSchema} for tool in tools_list.tools}
            return {"tools": tools_dict}
        except Exception as e:
            logger.error(f"Error listing tools: {e}")
            return {"error": str(e)}

    async def invoke_tool(self, tool_name: str, args: dict) -> dict:
        try:
            if not self.session:
                await self.connect()
            logger.info(f"Calling tool: {tool_name} with args: {args}")
            result = await self.session.call_tool(tool_name, args)

            if result.content:
                content_items = []
                for item in result.content:
                    if hasattr(item, 'text'):
                        try:
                            content_items.append(json.loads(item.text))
                        except json.JSONDecodeError:
                            content_items.append(item.text)
                if len(content_items) == 1:
                    return content_items[0]
                return {"results": content_items}

            return {"error": "No content in response"}
        except Exception as e:
            logger.error(f"Error invoking tool {tool_name}: {e}")
            return {"error": str(e)}

    # -------------------- DIRECT FLIGHT QUERY HANDLING (NO LLM) -------------------------
    async def handle_flight_query_direct(self, user_query: str, tool_name: str, tool_args: dict) -> dict:
        """
        Direct flight query handling without LLM planning
        """
        try:
            # Step 1: Pehle check karo kitne documents hain (multiple=True)
            count_args = tool_args.copy()
            count_args["multiple"] = True
            
            count_result = await self.invoke_tool(tool_name, count_args)
            
            if not count_result.get("ok"):
                return {"error": "Failed to fetch documents"}
            
            data = count_result.get("data", {})
            
            # Agar multiple documents return hue hain
            if isinstance(data, dict) and "documents" in data:
                documents = data.get("documents", [])
                count = data.get("count", 0)
                
                if count > 1:
                    # Multiple documents - routes extract karo
                    routes = []
                    for doc in documents:
                        flight_data = doc.get("flightLegState", {})
                        route = {
                            "startStation": flight_data.get("startStation", "Unknown"),
                            "endStation": flight_data.get("endStation", "Unknown"),
                            "scheduledStartTime": flight_data.get("scheduledStartTime", ""),
                            "flightStatus": flight_data.get("flightStatus", ""),
                            "document_index": len(routes)  # Reference ke liye
                        }
                        routes.append(route)
                    
                    return {
                        "needs_route_selection": True,
                        "available_routes": routes,
                        "total_documents": count,
                        "message": f"Found {count} documents. Please select a route.",
                        "original_tool": tool_name,
                        "original_args": tool_args
                    }
                elif count == 1:
                    # Single document - directly return karo
                    return {
                        "needs_route_selection": False,
                        "result": data.get("documents", [])[0] if documents else {}
                    }
                else:
                    return {"error": "No documents found"}
            else:
                # Single document case (existing behavior)
                return {
                    "needs_route_selection": False,
                    "result": data
                }
                
        except Exception as e:
            logger.error(f"Direct flight query handling failed: {e}")
            return {"error": str(e)}
    
    async def get_documents_by_route_selection(self, tool_name: str, tool_args: dict, selected_route: dict) -> dict:
        """
        Get specific document after user route selection
        """
        try:
            # Multiple documents fetch karo
            fetch_args = tool_args.copy()
            fetch_args["multiple"] = True
            
            result = await self.invoke_tool(tool_name, fetch_args)
            
            if not result.get("ok"):
                return {"error": "Failed to fetch documents"}
            
            data = result.get("data", {})
            documents = data.get("documents", [])
            
            # Selected route ke according document filter karo
            selected_start = selected_route.get("startStation")
            selected_end = selected_route.get("endStation")
            
            for doc in documents:
                flight_data = doc.get("flightLegState", {})
                if (flight_data.get("startStation") == selected_start and 
                    flight_data.get("endStation") == selected_end):
                    return {
                        "selected_route": selected_route,
                        "document": doc
                    }
            
            return {"error": "Selected route not found in documents"}
            
        except Exception as e:
            logger.error(f"Route selection query failed: {e}")
            return {"error": str(e)}

    # -------------------- LLM PLANNING & SUMMARIZATION -------------------------
    def plan_tools(self, user_query: str) -> dict:
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT_PLAN},
            {"role": "user", "content": user_query},
        ]

        res = self._call_azure_openai(messages, temperature=0.1)
        content = res.get("content")
        plan_usage = res.get("usage")
        
        if not content:
            logger.warning("⚠️ LLM returned empty response during plan generation.")
            return {"plan": [], "llm_usage": plan_usage}

        cleaned = content.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.strip("`")
            if cleaned.lower().startswith("json"):
                cleaned = cleaned[4:].strip()
            cleaned = cleaned.replace("```", "").strip()

        if cleaned != content:
            logger.debug(f"🔍 Cleaned LLM plan output:\n{cleaned}")

        try:
            plan = json.loads(cleaned)
            if isinstance(plan, dict) and "plan" in plan:
                return {"plan": plan["plan"], "llm_usage": plan_usage}
            else:
                logger.warning("⚠️ LLM output did not contain 'plan' key.")
                return {"plan": [], "llm_usage": plan_usage}
        except json.JSONDecodeError:
            logger.warning(f"❌ Could not parse LLM plan output after cleaning:\n{cleaned}")
            return {"plan": [], "llm_usage": plan_usage}

    def summarize_results(self, user_query: str, plan: list, results: list) -> dict:
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT_SUMMARIZE},
            {"role": "user", "content": f"Question:\n{user_query}"},
            {"role": "assistant", "content": f"Plan:\n{json.dumps(plan, indent=2)}"},
            {"role": "assistant", "content": f"Results:\n{json.dumps(results, indent=2)}"},
        ]
        res = self._call_azure_openai(messages, temperature=0.3)
        return {"summary": res.get("content"), "llm_usage": res.get("usage")}

    async def run_query(self, user_query: str) -> dict:
        """
        Full flow with proper token tracking for cost monitoring
        """
        try:
            logger.info(f"User query: {user_query}")
            plan_data = self.plan_tools(user_query)
            plan = plan_data.get("plan", [])
            planning_usage = plan_data.get("llm_usage")
            
            if not plan:
                return {
                    "error": "LLM did not produce a valid tool plan.",
                    "token_usage": {
                        "planning": planning_usage,
                        "summarization": None,
                        "total": planning_usage
                    }
                }

            # Execute the plan
            results = []
            for step in plan:
                tool = step.get("tool")
                args = step.get("arguments", {})
                
                # Clean up bad args
                args = {k: v for k, v in args.items() if v and str(v).strip().lower() != "unknown"}

                if tool == "raw_mongodb_query":
                    query_json = args.get("query_json", "")
                    if not query_json:
                        results.append({"raw_mongodb_query": {"error": "Empty query_json"}})
                        continue
                    args["limit"] = int(args.get("limit", 50))
                    logger.info(f"Executing raw MongoDB query: {query_json}")

                resp = await self.invoke_tool(tool, args)
                results.append({tool: resp})

            # Summarize results
            summary_data = self.summarize_results(user_query, plan, results)
            summarization_usage = summary_data.get("llm_usage")

            # Calculate total tokens for cost tracking
            def safe_int(value):
                try:
                    return int(value) if value is not None else 0
                except (ValueError, TypeError):
                    return 0

            total_tokens = {
                "prompt_tokens": safe_int(planning_usage and planning_usage.get("prompt_tokens")) + 
                                safe_int(summarization_usage and summarization_usage.get("prompt_tokens")),
                "completion_tokens": safe_int(planning_usage and planning_usage.get("completion_tokens")) + 
                                    safe_int(summarization_usage and summarization_usage.get("completion_tokens")),
                "total_tokens": safe_int(planning_usage and planning_usage.get("total_tokens")) + 
                               safe_int(summarization_usage and summarization_usage.get("total_tokens"))
            }

            return {
                "plan": plan,
                "results": results,
                "summary": {"summary": summary_data.get("summary")},
                "token_usage": {
                    "planning": planning_usage,
                    "summarization": summarization_usage,
                    "total": total_tokens
                }
            }
            
        except Exception as e:
            logger.error(f"Error in run_query: {e}")
            return {"error": str(e)}

    # -------------------- TEST FUNCTION FOR TIME CONVERSION -------------------------
    async def test_time_conversion(self):
        """
        Test converting a UTC time to local time
        """
        await self.connect()
        
        result = await self.invoke_tool("convert_utc_to_local_time", {
            "utc_time_str": "2024-06-23 13:25",
            "timezone_str": "Asia/Kolkata"
        })
        
        print("🕐 Time conversion test result:")
        print(json.dumps(result, indent=2))
        await self.disconnect()

def extract_flight_details_from_query(query: str) -> dict:
    """
    Extract flight details from user query without LLM
    """
    details = {}
    
    # Extract carrier
    carrier_match = re.search(r'\b(6E|AI|SG|UK|G8|IX|I5)\b', query.upper())
    if carrier_match:
        details["carrier"] = carrier_match.group(1)
    
    # Extract flight number
    flight_match = re.search(r'flight\s+(\d+)', query.lower())
    if flight_match:
        details["flight_number"] = flight_match.group(1)
    else:
        # Direct number search
        num_match = re.search(r'\b(\d{3,4})\b', query)
        if num_match:
            details["flight_number"] = num_match.group(1)
    
    # Extract date
    date_match = re.search(r'(\d{4}-\d{2}-\d{2})', query)
    if date_match:
        details["date_of_origin"] = date_match.group(1)
    
    return details
