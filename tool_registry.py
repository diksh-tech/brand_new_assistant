# tool_registry.py

TOOLS = {
    "health_check": {
        "args": [],
        "desc": "Simple health check for orchestrators and clients. Attempts a cheap DB ping.",
    },
    "get_flight_basic_info": {
        "args": ["carrier", "flight_number", "date_of_origin", "multiple"],
        "desc": "Fetch basic flight information including carrier, flight number, date, stations, times, and status. Use multiple=True for all matching documents.",
    },
    "get_operation_times": {
        "args": ["carrier", "flight_number", "date_of_origin", "multiple"],
        "desc": "Return estimated and actual operation times for a flight including takeoff, landing, block times, StartTimeOffset, EndTimeOffset. Use multiple=True for all matching documents.",
    },
    "get_equipment_info": {
        "args": ["carrier", "flight_number", "date_of_origin", "multiple"],
        "desc": "Get aircraft equipment details including aircraft type, registration (tail number), and configuration. Use multiple=True for all matching documents.",
    },
    "get_delay_summary": {
        "args": ["carrier", "flight_number", "date_of_origin", "multiple"],
        "desc": "Summarize delay reasons, durations, and total delay time for a specific flight. Use multiple=True for all matching documents.",
    },
    "get_fuel_summary": {
        "args": ["carrier", "flight_number", "date_of_origin", "multiple"],
        "desc": "Retrieve fuel summary including planned vs actual fuel for takeoff, landing, and total consumption. Use multiple=True for all matching documents.",
    },
    "get_passenger_info": {
        "args": ["carrier", "flight_number", "date_of_origin", "multiple"],
        "desc": "Get passenger count and connection information for the flight. Use multiple=True for all matching documents.",
    },
    "get_crew_info": {
        "args": ["carrier", "flight_number", "date_of_origin", "multiple"],
        "desc": "Get crew connections and details for the flight. Use multiple=True for all matching documents.",
    },
    "raw_mongodb_query": {
        "args": ["query_json", "projection", "limit", "multiple"],
        "desc": "Execute a raw MongoDB query (stringified JSON) with optional projection. Supports intelligent LLM-decided projections to reduce payload size based on query intent. Use multiple=True for all matching documents.",
    },
    "run_aggregated_query": {
        "args": ["query_type", "carrier", "field", "start_date", "end_date", "filter_json"],
        "desc": "Run statistical or comparative MongoDB aggregation queries for counts, averages, sums, etc.",
    },
    "convert_utc_to_local_time": {
        "args": ["utc_time_str", "timezone_str"],
        "desc": "Convert UTC time to local time. Defaults to IST (UTC+5:30). Accepts formats: 'YYYY-MM-DD HH:MM' or ISO.",
    },
}
