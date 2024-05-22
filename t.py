from DatabaseManager import DatabaseManager

# List initialization
blocked_sellers = []
skipped_keywords = []
skipped_cities = ['Colorado Springs', "Monument", "Fort Collins"]
searches = []
special_words = ["free", "today"]  # List of words to ignore when they appear next to skipped keywords
keyword_found = False
result = ""
# Query setup
query = "'20' and 40' Shipping Containers Delivered - Prices Vary by Location'"
queryDesc = ("\"Message me with the delivery Zip Code for a Free Quote today."
             "-20' and 40' One Trip and Quality Used Containers)"
             "-Veteran Owned and Operated"
             "-Financing Available"
             "Sizes Available:"
             "20' Standard - 20' x 8' x 8'6"
             "40' Standard - 40' x 8' x 8'6"
             "40' High Cube - 40' x 8' x 9'6"
             "Stephen Kristia"
             "Freedom Cone"
             "(9_1_4) 6_4_5-6_6_7_8")
queryModified = f"{query} + {queryDesc}"

# Database operations
with DatabaseManager() as db:
    # Retrieve banned sellers
    db.execute_query('SELECT name FROM blocked_sellers')
    rows = db.fetch_all()
    blocked_sellers.extend([row[0] for row in rows])

    # Retrieve skipped keywords
    db.execute_query('SELECT keyword FROM blacklisted_keywords')
    rows = db.fetch_all()
    skipped_keywords.extend(row[0] for row in rows)

    db.execute_query('SELECT search_text FROM queries')
    rows = db.fetch_all()
    searches.extend(row[0] for row in rows)

# Check if the query is from a blocked seller
if query in blocked_sellers:
    print(f"Seller blocked: {query}...🚫Skipped🚫")
else:
    # Check if any of the skipped keywords are present in the title or description of the listing
    skipped_keyword_found = False
    for keyword in skipped_keywords:

        # Convert the keyword to lowercase
        lower_keyword = keyword.lower()
        # Create a combined string of the title and description in lowercase
        combined_text = queryModified.lower()

        # Check if the lowercased keyword is in the combined text
        if lower_keyword in combined_text:
            # If a skipped keyword is found, we note that and break the loop
            #print(keyword)
            skipped_keyword_found = True
            break

    # Check if any of the search keywords that are not special words are present in the description
    search_keyword_found = False
    for keyword in searches:
        # Convert the keyword to lowercase
        lower_keyword = keyword.lower()

        # Check if the keyword is not in the special words list
        if lower_keyword not in special_words:
            print(lower_keyword)
            # Check if the lowercased keyword is in the listing's description
            if lower_keyword in queryDesc.lower():

                # If a search keyword is found, we note that and break the loop
                search_keyword_found = True
                break

    # Combine the results of the checks into the final condition for the elif statement
    # The condition is True if any skipped keyword is found AND no search keywords are found
    elif_condition = skipped_keyword_found and not search_keyword_found
    # Print the result based on the presence of a blacklisted keyword
    if elif_condition:
        print("")
    else:
        print(f"Listing passed")