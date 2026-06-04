module.exports = {
  apps: [
    {
      name: "auto-trader-dashboard",
      script: ".venv/bin/streamlit",
      args: "run dashboard/app.py --server.port 8501 --server.headless true",
      cwd: "/app/auto-trader",   // ← 실제 서버 경로로 변경

      autorestart: true,
      watch: false,
      max_restarts: 10,
      restart_delay: 5000,

      out_file: "logs/dashboard_out.log",
      error_file: "logs/dashboard_err.log",
      log_date_format: "YYYY-MM-DD HH:mm:ss",
      merge_logs: true,

      env: {
        PYTHONUNBUFFERED: "1",
        PYTHONIOENCODING: "utf-8",
      },
    },
  ],
};
