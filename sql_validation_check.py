from logger_setup import logger

def validate_sql(sql_query: str) -> tuple[bool, str]:
    """
    Validates a SQL query to make sure it is safe to execute.
    Returns:
        tuple[bool, str]: (is_valid, message)
    """
    if not isinstance(sql_query, str):
        return False, "Error: SQL query must be a string."
        
    # Convert query to uppercase for easier matching
    sql_upper = sql_query.upper()
    sql_stripped = sql_upper.strip()

    # 1. Must be SELECT only
    if not sql_stripped.startswith("SELECT"):
        logger.warning("SQL validation failed: Non-SELECT operation", query=sql_upper)
        return False, "Error: Query must be a SELECT statement. INSERT, UPDATE, DELETE, DROP, ALTER, etc. are rejected."
        
    # Replace common punctuation with spaces so we can extract whole words
    clean_query = sql_upper
    for char in ['(', ')', '[', ']', ',', ';', '=', '*', '\n', '\t']:
        clean_query = clean_query.replace(char, ' ')
        
    # Split the query into individual words
    words = clean_query.split()
    
    # 2. No dangerous keywords
    forbidden_words = [
        "INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "EXEC", 
        "GRANT", "REVOKE", "SHUTDOWN"
    ]
    
    for word in words:
        if word in forbidden_words:
            logger.warning("SQL validation failed: Forbidden keyword", keyword=word, query=sql_upper)
            return False, f"Error: Dangerous keyword '{word}' is not allowed."
            
        if word.startswith("XP_") or word.startswith("SP_"):
            logger.warning("SQL validation failed: Forbidden prefix", keyword=word, query=sql_upper)
            return False, f"Error: Dangerous prefix 'xp_' or 'sp_' found in '{word}'."
            
    # 3. No system tables
    system_tables = ["SQLITE_MASTER"]
    for word in words:
        if word in system_tables:
            logger.warning("SQL validation failed: System table access", keyword=word, query=sql_upper)
            return False, f"Error: Accessing system table '{word.lower()}' is not allowed."
            
    # If all checks pass
    logger.info("SQL validation passed", query=sql_upper)
    return True, "Query is valid."
