import psycopg

conn_str = "postgresql://eval_admin:eval_secret_pass@127.0.0.1:5433/impark_evaluation"
with psycopg.connect(conn_str) as conn:
    with conn.cursor() as cur:
        cur.execute("""
            SELECT 
                count(*),
                avg(groundedness_score),
                avg(hallucination_rate),
                avg(tool_call_accuracy),
                avg(graph_retrieval_time_ms)
            FROM case_evaluation_metrics;
        """)
        row = cur.fetchone()
        print("=== CASE EVALUATION METRICS IN POSTGRESQL ===")
        print(f"Total Rows:                   {row[0]}")
        print(f"Average Groundedness Score:   {row[1]:.2%}")
        print(f"Average Hallucination Rate:   {row[2]:.2%}")
        print(f"Average Tool Call Accuracy:   {row[3]:.2%}")
        print(f"Average Graph Retrieval Time: {row[4]:.2f} ms")

        cur.execute("SELECT * FROM aggregate_evaluation_metrics ORDER BY id DESC LIMIT 5;")
        agg_rows = cur.fetchall()
        print("\n=== AGGREGATE EVALUATION METRICS IN POSTGRESQL ===")
        for ar in agg_rows:
            print("Aggregate row:", ar)
