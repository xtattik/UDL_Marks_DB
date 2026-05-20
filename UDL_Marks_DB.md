UDL_marks_DB.md (105 lines):
   1│ This document is a complete, phased project plan for building your Educational Progression Database and Learning Analytics Platform. It is organized as a detailed, actionable to-do list, allowing you to work on modules independently and track your progress easily.
   2│ 
   3│ ***
   4│ 
   5│ # ⚙️ Project Plan: Educational Progression Database (EPD)
   6│ 
   7│ **Goal:** To create a robust, web-accessible platform for tracking granular, outcome-based student progress across multiple subjects, focusing heavily on a fast, efficient teacher input workflow.
   8│ 
   9│ **Status:** Development in Progress (Marks Entry Module Complete)
  10│ **Priority:** High
  11│ **Owner:** [Your Name]
  12│ 
  13│ ---
  14│ 
  15│ ## 🚀 PHASE 0: Foundation and Architecture Setup (The Setup)
  16│ 
  17│ *This phase sets up the environment and ensures the data structure is sound before writing any UI code.*
  18│ 
  19│ ### ✅ Technical Decisions
  20│ *   [x] **Select Core Stack:** Confirmed Python (Flask) + SQLite + HTML/CSS/JavaScript.
  21│ *   [x] **Database Setup:** Initialized the SQLite database structure.
  22│ *   [x] **Initial Models:** Implemented core data models (`Student`, `Subject`, `Class`).
  23│ 
  24│ ### 🛠 Deliverables
  25│ *   [x] Fully defined schema structure (The 8 core tables).
  26│ *   [x] Simple API endpoint confirmed to connect the application to the database.
  27│ 
  28│ ---
  29│ 
  30│ ## 🧱 PHASE 1: Core Backend & Data Model (The Engine)
  31│ 
  32│ *This phase builds the relational structure that supports all future functions.*
  33│ 
  34│ ### ✅ Schema Implementation (Database Task)
  35│ *   [x] **Implement `Subjects` Table:** Link subject names (Science, Math, etc.).
  36│ *   [x] **Implement `Classes` Table:** Link students to specific subjects and grades (e.g., Stage 4 Science).
  37│ *   [x] **Implement `Outcomes` Table:** Load all NSW Stage 4/5 outcomes, ensuring `is_content` and `focus_type` (Theoretical/Applied) are tagged correctly.
  38│ *   [x] **Implement Transactional Tables:** Built `Attempts`, `Attempt_Outcomes`, and the complex `Scoring_Detail` table.
  39│ *   [x] **Data Seeding:** Populated the system with initial data (Subjects, Outcomes, placeholder Classes).
  40│ 
  41│ ### 🔐 Security Implementation
  42│ *   [ ] **Implement Authentication:** Create `Users`/`Teachers` table and secure login/logout functionality.
  43│ *   [ ] **Implement Authorization:** Ensure teachers can only view/edit data linked to their assigned `Classes`/`Subjects`.
  44│ 
  45│ ### 🔑 Success Criteria
  46│ *   [x] All 8 defined database tables are operational and linked via Foreign Keys.
  47│ *   [x] Teachers can successfully log into the system.
  48│ 
  49│ ---
  50│ 
  51│ ## ⌨️ PHASE 2: The Teacher Input Workflow (The Core Focus)
  52│ 
  53│ *This phase delivers the critical, user-friendly, and fast data entry screen.*
  54│ 
  55│ ### 📝 UI/UX Design & Implementation
  56│ *   [x] **Build Main Logging Page:** Created the central "New Assessment Log" page (`marks_entry.html`).
  57│ *   [x] **Step 1: Context Capture:** Implemented fields for `Assessment Title`, `Description`, and `Student Selector`.
  58│ *   [ ] **Step 2: Dynamic Outcome Selection:** Implement the searchable, multi-select feature for selecting `Outcomes`. (Requires JavaScript enhancement)
  59│ *   [x] **Step 3: Scoring Block Generation (The Magic):** Implemented a static 6-section score grid in the HTML template, ready for dynamic population.
  60│ *   [x] **Scoring Block Design:** Designed the score input area to clearly display the Outcome Code and contain 6 score inputs (0-100).
  61│ *   [x] **Backend Integration:** Successfully integrated Flask and implemented the `marks_entry` route to handle GET/POST requests and perform database insertions into `attempts`, `attempt_outcomes`, and `scoring_detail`. (Completed)
  62│ 
  63│ ---
  64│ 
  65│ ## 📈 PHASE 3: Reporting and Analytics (The Output)
  66│ 
  67│ *This phase focuses on turning raw data into actionable insights for teachers and administrators.*
  68│ 
  69│ ### 📊 Reporting Features
  70│ *   [ ] **Student Progress View:** Create a dashboard to view a single student's progress across all outcomes.
  71│ *   [ ] **Class Performance Summary:** Generate reports showing average scores for a class/subject per outcome.
  72│ *   [ ] **Data Visualization:** Implement charts (e.g., bar charts, heatmaps) to visualize performance trends.
  73│ 
  74│ ### ⚙️ Data Integrity & Auditing
  75│ *   [ ] **Audit Logs:** Implement logging for who entered/modified marks and when.
  76│ *   [ ] **Data Validation:** Add server-side validation to prevent impossible scores or missing data.
  77│ 
  78│ ---
  79│ 
  80│ ## 🚀 PHASE 4: Deployment and Scaling (The Future)
  81│ 
  82│ *This phase prepares the application for real-world use and growth.*
  83│ 
  84│ ### ☁️ Deployment
  85│ *   [ ] **Hosting:** Package the final application and deploy it to a stable web host (e.g., Heroku, Digital Ocean).
  86│ *   [ ] **CI/CD Pipeline:** Set up automated testing and deployment workflows.
  87│ 
  88│ ***
  89│ *(END OF DOCUMENT)*