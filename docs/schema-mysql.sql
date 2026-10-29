-- Agent Center MySQL 8 DDL
-- 由 scripts/export_ddl.py 生成，请由 DBA 审核后执行。
-- 所有业务表均包含 tenant_id，用于多租户隔离。

SET NAMES utf8mb4;

CREATE TABLE agent_definition (
	id BIGINT NOT NULL AUTO_INCREMENT, 
	code VARCHAR(100) NOT NULL, 
	name VARCHAR(200) NOT NULL, 
	domain_code VARCHAR(100) NOT NULL, 
	description TEXT, 
	lifecycle VARCHAR(20) NOT NULL, 
	current_version_id BIGINT, 
	tenant_id VARCHAR(64) NOT NULL, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uk_agent_tenant_code UNIQUE (tenant_id, code)
);

CREATE INDEX ix_agent_definition_domain_code ON agent_definition (domain_code);

CREATE INDEX ix_agent_definition_lifecycle ON agent_definition (lifecycle);

CREATE INDEX ix_agent_definition_tenant_id ON agent_definition (tenant_id);



CREATE TABLE agent_version (
	id BIGINT NOT NULL AUTO_INCREMENT, 
	agent_id BIGINT NOT NULL, 
	version_no INTEGER NOT NULL, 
	config_json JSON NOT NULL, 
	prompt_version_id BIGINT, 
	model_policy_json JSON NOT NULL, 
	tool_bindings_json JSON NOT NULL, 
	knowledge_scopes_json JSON NOT NULL, 
	status VARCHAR(20) NOT NULL, 
	published_at DATETIME, 
	tenant_id VARCHAR(64) NOT NULL, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uk_agent_version UNIQUE (agent_id, version_no)
);

CREATE INDEX ix_agent_version_agent_id ON agent_version (agent_id);

CREATE INDEX ix_agent_version_tenant_id ON agent_version (tenant_id);



CREATE TABLE audit_log (
	id BIGINT NOT NULL AUTO_INCREMENT, 
	user_id VARCHAR(64), 
	action VARCHAR(100) NOT NULL, 
	resource_type VARCHAR(50) NOT NULL, 
	resource_id VARCHAR(100), 
	detail_json JSON, 
	created_at DATETIME NOT NULL, 
	tenant_id VARCHAR(64) NOT NULL, 
	PRIMARY KEY (id)
);

CREATE INDEX ix_audit_log_tenant_id ON audit_log (tenant_id);



CREATE TABLE badcase (
	id BIGINT NOT NULL AUTO_INCREMENT, 
	feedback_id BIGINT, 
	run_id VARCHAR(64), 
	status VARCHAR(20) NOT NULL, 
	description TEXT, 
	eval_case_id BIGINT, 
	tenant_id VARCHAR(64) NOT NULL, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id)
);

CREATE INDEX ix_badcase_run_id ON badcase (run_id);

CREATE INDEX ix_badcase_tenant_id ON badcase (tenant_id);



CREATE TABLE citation (
	id BIGINT NOT NULL AUTO_INCREMENT, 
	run_id VARCHAR(64) NOT NULL, 
	message_id BIGINT, 
	document_id VARCHAR(64) NOT NULL, 
	chunk_id VARCHAR(64) NOT NULL, 
	title VARCHAR(300) NOT NULL, 
	section VARCHAR(300), 
	source_url TEXT, 
	quote TEXT, 
	effective_status VARCHAR(20), 
	created_at DATETIME NOT NULL, 
	tenant_id VARCHAR(64) NOT NULL, 
	PRIMARY KEY (id)
);

CREATE INDEX ix_citation_run_id ON citation (run_id);

CREATE INDEX ix_citation_tenant_id ON citation (tenant_id);



CREATE TABLE conversation (
	id BIGINT NOT NULL AUTO_INCREMENT, 
	user_id VARCHAR(64) NOT NULL, 
	channel VARCHAR(32) NOT NULL, 
	status VARCHAR(32) NOT NULL, 
	current_agent_code VARCHAR(100), 
	agent_group_code VARCHAR(100), 
	context_summary TEXT, 
	session_state_json JSON NOT NULL, 
	last_message_at DATETIME, 
	expires_at DATETIME, 
	tenant_id VARCHAR(64) NOT NULL, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id)
);

CREATE INDEX ix_conversation_tenant_id ON conversation (tenant_id);

CREATE INDEX ix_conversation_user_id ON conversation (user_id);



CREATE TABLE conversation_turn (
	id BIGINT NOT NULL AUTO_INCREMENT, 
	conversation_id BIGINT NOT NULL, 
	turn_no INTEGER NOT NULL, 
	status VARCHAR(32) NOT NULL, 
	user_message_id BIGINT, 
	assistant_message_id BIGINT, 
	started_at DATETIME, 
	ended_at DATETIME, 
	tenant_id VARCHAR(64) NOT NULL, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uk_turn_conversation_no UNIQUE (conversation_id, turn_no)
);

CREATE INDEX ix_conversation_turn_conversation_id ON conversation_turn (conversation_id);

CREATE INDEX ix_conversation_turn_tenant_id ON conversation_turn (tenant_id);



CREATE TABLE eval_case (
	id BIGINT NOT NULL AUTO_INCREMENT, 
	dataset_id BIGINT NOT NULL, 
	question TEXT NOT NULL, 
	expected_answer TEXT, 
	expected_doc_ids_json JSON NOT NULL, 
	tags_json JSON NOT NULL, 
	tenant_id VARCHAR(64) NOT NULL, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id)
);

CREATE INDEX ix_eval_case_dataset_id ON eval_case (dataset_id);

CREATE INDEX ix_eval_case_tenant_id ON eval_case (tenant_id);



CREATE TABLE eval_dataset (
	id BIGINT NOT NULL AUTO_INCREMENT, 
	code VARCHAR(100) NOT NULL, 
	name VARCHAR(200) NOT NULL, 
	domain_code VARCHAR(100), 
	tenant_id VARCHAR(64) NOT NULL, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uk_eval_dataset_tenant_code UNIQUE (tenant_id, code)
);

CREATE INDEX ix_eval_dataset_code ON eval_dataset (code);

CREATE INDEX ix_eval_dataset_tenant_id ON eval_dataset (tenant_id);



CREATE TABLE eval_result (
	id BIGINT NOT NULL AUTO_INCREMENT, 
	eval_run_id BIGINT NOT NULL, 
	case_id BIGINT NOT NULL, 
	score DOUBLE NOT NULL, 
	passed BOOL, 
	actual_answer TEXT, 
	detail_json JSON, 
	tenant_id VARCHAR(64) NOT NULL, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id)
);

CREATE INDEX ix_eval_result_eval_run_id ON eval_result (eval_run_id);

CREATE INDEX ix_eval_result_tenant_id ON eval_result (tenant_id);



CREATE TABLE eval_run (
	id BIGINT NOT NULL AUTO_INCREMENT, 
	dataset_id BIGINT NOT NULL, 
	prompt_version_id BIGINT, 
	agent_version_id BIGINT, 
	status VARCHAR(20) NOT NULL, 
	metrics_json JSON, 
	finished_at DATETIME, 
	tenant_id VARCHAR(64) NOT NULL, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id)
);

CREATE INDEX ix_eval_run_dataset_id ON eval_run (dataset_id);

CREATE INDEX ix_eval_run_tenant_id ON eval_run (tenant_id);



CREATE TABLE feedback (
	id BIGINT NOT NULL AUTO_INCREMENT, 
	conversation_id BIGINT, 
	message_id BIGINT, 
	run_id VARCHAR(64), 
	rating VARCHAR(20) NOT NULL, 
	reason VARCHAR(100), 
	comment TEXT, 
	user_id VARCHAR(64), 
	tenant_id VARCHAR(64) NOT NULL, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id)
);

CREATE INDEX ix_feedback_conversation_id ON feedback (conversation_id);

CREATE INDEX ix_feedback_run_id ON feedback (run_id);

CREATE INDEX ix_feedback_tenant_id ON feedback (tenant_id);



CREATE TABLE knowledge_chunk (
	id BIGINT NOT NULL AUTO_INCREMENT, 
	chunk_id VARCHAR(64) NOT NULL, 
	document_id BIGINT NOT NULL, 
	document_version INTEGER NOT NULL, 
	title VARCHAR(300) NOT NULL, 
	section VARCHAR(300), 
	content TEXT NOT NULL, 
	domain_code VARCHAR(100), 
	region_code VARCHAR(20), 
	effective_from DATETIME, 
	effective_to DATETIME, 
	authority_level INTEGER NOT NULL, 
	source_url TEXT, 
	content_hash VARCHAR(64) NOT NULL, 
	status VARCHAR(20) NOT NULL, 
	embedding_ref VARCHAR(64), 
	tenant_id VARCHAR(64) NOT NULL, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (chunk_id)
);

CREATE INDEX ix_knowledge_chunk_document_id ON knowledge_chunk (document_id);

CREATE INDEX ix_knowledge_chunk_domain_code ON knowledge_chunk (domain_code);

CREATE INDEX ix_knowledge_chunk_region_code ON knowledge_chunk (region_code);

CREATE INDEX ix_knowledge_chunk_tenant_id ON knowledge_chunk (tenant_id);



CREATE TABLE knowledge_document (
	id BIGINT NOT NULL AUTO_INCREMENT, 
	space_id BIGINT NOT NULL, 
	document_code VARCHAR(100) NOT NULL, 
	title VARCHAR(300) NOT NULL, 
	version_no INTEGER NOT NULL, 
	status VARCHAR(20) NOT NULL, 
	region_code VARCHAR(20), 
	authority_level INTEGER NOT NULL, 
	effective_from DATETIME, 
	effective_to DATETIME, 
	source_url TEXT, 
	content_hash VARCHAR(64), 
	tenant_id VARCHAR(64) NOT NULL, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id)
);

CREATE INDEX ix_knowledge_document_space_id ON knowledge_document (space_id);

CREATE INDEX ix_knowledge_document_tenant_id ON knowledge_document (tenant_id);



CREATE TABLE knowledge_route_rule (
	id BIGINT NOT NULL AUTO_INCREMENT, 
	domain_code VARCHAR(100) NOT NULL, 
	intent_keywords_json JSON NOT NULL, 
	space_ids_json JSON NOT NULL, 
	priority INTEGER NOT NULL, 
	tenant_id VARCHAR(64) NOT NULL, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id)
);

CREATE INDEX ix_knowledge_route_rule_tenant_id ON knowledge_route_rule (tenant_id);



CREATE TABLE knowledge_space (
	id BIGINT NOT NULL AUTO_INCREMENT, 
	code VARCHAR(100) NOT NULL, 
	name VARCHAR(200) NOT NULL, 
	layer VARCHAR(20) NOT NULL, 
	domain_code VARCHAR(100), 
	agent_id BIGINT, 
	tenant_id VARCHAR(64) NOT NULL, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id)
);

CREATE INDEX ix_knowledge_space_code ON knowledge_space (code);

CREATE INDEX ix_knowledge_space_tenant_id ON knowledge_space (tenant_id);



CREATE TABLE knowledge_sync_task (
	id BIGINT NOT NULL AUTO_INCREMENT, 
	space_id BIGINT NOT NULL, 
	source_type VARCHAR(20) NOT NULL, 
	source_ref VARCHAR(500), 
	status VARCHAR(20) NOT NULL, 
	retry_count INTEGER NOT NULL, 
	error_message TEXT, 
	checkpoint_json JSON NOT NULL, 
	finished_at DATETIME, 
	tenant_id VARCHAR(64) NOT NULL, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id)
);

CREATE INDEX ix_knowledge_sync_task_space_id ON knowledge_sync_task (space_id);

CREATE INDEX ix_knowledge_sync_task_tenant_id ON knowledge_sync_task (tenant_id);



CREATE TABLE memory_embedding (
	id BIGINT NOT NULL AUTO_INCREMENT, 
	memory_item_id BIGINT NOT NULL, 
	vector_ref VARCHAR(100) NOT NULL, 
	content_hash VARCHAR(64) NOT NULL, 
	status VARCHAR(20) NOT NULL, 
	tenant_id VARCHAR(64) NOT NULL, 
	PRIMARY KEY (id)
);

CREATE INDEX ix_memory_embedding_memory_item_id ON memory_embedding (memory_item_id);

CREATE INDEX ix_memory_embedding_tenant_id ON memory_embedding (tenant_id);



CREATE TABLE memory_episode (
	id BIGINT NOT NULL AUTO_INCREMENT, 
	user_id VARCHAR(64) NOT NULL, 
	conversation_id BIGINT, 
	summary TEXT NOT NULL, 
	event_json JSON NOT NULL, 
	occurred_at DATETIME, 
	tenant_id VARCHAR(64) NOT NULL, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id)
);

CREATE INDEX ix_memory_episode_tenant_id ON memory_episode (tenant_id);

CREATE INDEX ix_memory_episode_user_id ON memory_episode (user_id);



CREATE TABLE memory_item (
	id BIGINT NOT NULL AUTO_INCREMENT, 
	user_id VARCHAR(64) NOT NULL, 
	memory_type VARCHAR(20) NOT NULL, 
	subject VARCHAR(200) NOT NULL, 
	predicate VARCHAR(200) NOT NULL, 
	object_value TEXT NOT NULL, 
	source_type VARCHAR(32), 
	source_message_id BIGINT, 
	confidence FLOAT NOT NULL, 
	importance FLOAT NOT NULL, 
	valid_from DATETIME, 
	valid_to DATETIME, 
	expires_at DATETIME, 
	version_no INTEGER NOT NULL, 
	status VARCHAR(20) NOT NULL, 
	embedding_ref VARCHAR(64), 
	tenant_id VARCHAR(64) NOT NULL, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id)
);

CREATE INDEX ix_memory_item_tenant_id ON memory_item (tenant_id);

CREATE INDEX ix_memory_item_user_id ON memory_item (user_id);



CREATE TABLE message (
	id BIGINT NOT NULL AUTO_INCREMENT, 
	conversation_id BIGINT NOT NULL, 
	turn_id BIGINT, 
	`role` VARCHAR(20) NOT NULL, 
	content_type VARCHAR(20) NOT NULL, 
	content TEXT NOT NULL, 
	content_json JSON, 
	token_count INTEGER NOT NULL, 
	safety_status VARCHAR(20), 
	client_message_id VARCHAR(100), 
	tenant_id VARCHAR(64) NOT NULL, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id)
);

CREATE INDEX ix_message_client_message_id ON message (client_message_id);

CREATE INDEX ix_message_conversation_id ON message (conversation_id);

CREATE INDEX ix_message_tenant_id ON message (tenant_id);

CREATE INDEX ix_message_turn_id ON message (turn_id);



CREATE TABLE model_provider (
	id BIGINT NOT NULL AUTO_INCREMENT, 
	provider_code VARCHAR(50) NOT NULL, 
	model_alias VARCHAR(100) NOT NULL, 
	capabilities_json JSON NOT NULL, 
	enabled BOOL NOT NULL, 
	tenant_id VARCHAR(64) NOT NULL, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id)
);

CREATE INDEX ix_model_provider_model_alias ON model_provider (model_alias);

CREATE INDEX ix_model_provider_tenant_id ON model_provider (tenant_id);



CREATE TABLE model_route_policy (
	id BIGINT NOT NULL AUTO_INCREMENT, 
	policy_code VARCHAR(100) NOT NULL, 
	task_type VARCHAR(50) NOT NULL, 
	primary_model VARCHAR(100) NOT NULL, 
	fallback_model VARCHAR(100), 
	timeout_ms INTEGER NOT NULL, 
	max_retries INTEGER NOT NULL, 
	temperature DOUBLE NOT NULL, 
	extra_json JSON NOT NULL, 
	tenant_id VARCHAR(64) NOT NULL, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id)
);

CREATE INDEX ix_model_route_policy_policy_code ON model_route_policy (policy_code);

CREATE INDEX ix_model_route_policy_tenant_id ON model_route_policy (tenant_id);



CREATE TABLE model_usage_log (
	id BIGINT NOT NULL AUTO_INCREMENT, 
	run_id VARCHAR(64), 
	model_alias VARCHAR(100) NOT NULL, 
	provider_code VARCHAR(50), 
	prompt_version_id BIGINT, 
	token_input INTEGER NOT NULL, 
	token_output INTEGER NOT NULL, 
	token_cached INTEGER NOT NULL, 
	first_token_ms INTEGER NOT NULL, 
	latency_ms INTEGER NOT NULL, 
	estimated_cost DOUBLE NOT NULL, 
	status VARCHAR(20) NOT NULL, 
	detail TEXT, 
	tenant_id VARCHAR(64) NOT NULL, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id)
);

CREATE INDEX ix_model_usage_log_run_id ON model_usage_log (run_id);

CREATE INDEX ix_model_usage_log_tenant_id ON model_usage_log (tenant_id);



CREATE TABLE notification (
	id BIGINT NOT NULL AUTO_INCREMENT, 
	user_id VARCHAR(64) NOT NULL, 
	notification_type VARCHAR(50) NOT NULL, 
	title VARCHAR(200) NOT NULL, 
	content TEXT NOT NULL, 
	payload_json JSON NOT NULL, 
	scheduled_at DATETIME, 
	status VARCHAR(20) NOT NULL, 
	sent_at DATETIME, 
	tenant_id VARCHAR(64) NOT NULL, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id)
);

CREATE INDEX ix_notification_notification_type ON notification (notification_type);

CREATE INDEX ix_notification_scheduled_at ON notification (scheduled_at);

CREATE INDEX ix_notification_status ON notification (status);

CREATE INDEX ix_notification_tenant_id ON notification (tenant_id);

CREATE INDEX ix_notification_user_id ON notification (user_id);



CREATE TABLE prompt_binding (
	id BIGINT NOT NULL AUTO_INCREMENT, 
	agent_id BIGINT NOT NULL, 
	prompt_template_id BIGINT NOT NULL, 
	prompt_version_id BIGINT, 
	tenant_id VARCHAR(64) NOT NULL, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id)
);

CREATE INDEX ix_prompt_binding_agent_id ON prompt_binding (agent_id);

CREATE INDEX ix_prompt_binding_tenant_id ON prompt_binding (tenant_id);



CREATE TABLE prompt_template (
	id BIGINT NOT NULL AUTO_INCREMENT, 
	code VARCHAR(100) NOT NULL, 
	name VARCHAR(200) NOT NULL, 
	layer VARCHAR(20) NOT NULL, 
	current_version_id BIGINT, 
	tenant_id VARCHAR(64) NOT NULL, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uk_prompt_tenant_code UNIQUE (tenant_id, code)
);

CREATE INDEX ix_prompt_template_code ON prompt_template (code);

CREATE INDEX ix_prompt_template_tenant_id ON prompt_template (tenant_id);



CREATE TABLE prompt_version (
	id BIGINT NOT NULL AUTO_INCREMENT, 
	template_id BIGINT NOT NULL, 
	version_no INTEGER NOT NULL, 
	content TEXT NOT NULL, 
	variables_json JSON NOT NULL, 
	output_schema_json JSON, 
	status VARCHAR(20) NOT NULL, 
	environment VARCHAR(20) NOT NULL, 
	eval_result_json JSON, 
	published_at DATETIME, 
	tenant_id VARCHAR(64) NOT NULL, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id)
);

CREATE INDEX ix_prompt_version_template_id ON prompt_version (template_id);

CREATE INDEX ix_prompt_version_tenant_id ON prompt_version (tenant_id);



CREATE TABLE run (
	id VARCHAR(64) NOT NULL, 
	conversation_id BIGINT NOT NULL, 
	turn_id BIGINT, 
	agent_version_id BIGINT, 
	agent_code VARCHAR(100), 
	parent_run_id VARCHAR(64), 
	trace_id VARCHAR(64) NOT NULL, 
	status VARCHAR(32) NOT NULL, 
	current_step INTEGER NOT NULL, 
	step_budget INTEGER NOT NULL, 
	token_budget INTEGER NOT NULL, 
	tool_call_count INTEGER NOT NULL, 
	token_input BIGINT NOT NULL, 
	token_output BIGINT NOT NULL, 
	started_at DATETIME, 
	ended_at DATETIME, 
	error_code VARCHAR(100), 
	error_message TEXT, 
	tenant_id VARCHAR(64) NOT NULL, 
	PRIMARY KEY (id)
);

CREATE INDEX ix_run_conversation_id ON run (conversation_id);

CREATE INDEX ix_run_tenant_id ON run (tenant_id);

CREATE INDEX ix_run_trace_id ON run (trace_id);



CREATE TABLE run_checkpoint (
	id BIGINT NOT NULL AUTO_INCREMENT, 
	run_id VARCHAR(64) NOT NULL, 
	checkpoint_version INTEGER NOT NULL, 
	step_no INTEGER NOT NULL, 
	state_json JSON NOT NULL, 
	created_at DATETIME NOT NULL, 
	tenant_id VARCHAR(64) NOT NULL, 
	PRIMARY KEY (id)
);

CREATE INDEX ix_run_checkpoint_run_id ON run_checkpoint (run_id);

CREATE INDEX ix_run_checkpoint_tenant_id ON run_checkpoint (tenant_id);



CREATE TABLE run_event (
	id BIGINT NOT NULL AUTO_INCREMENT, 
	run_id VARCHAR(64) NOT NULL, 
	seq INTEGER NOT NULL, 
	event VARCHAR(50) NOT NULL, 
	data_json JSON NOT NULL, 
	created_at DATETIME NOT NULL, 
	tenant_id VARCHAR(64) NOT NULL, 
	PRIMARY KEY (id)
);

CREATE INDEX ix_run_event_run_id ON run_event (run_id);

CREATE INDEX ix_run_event_tenant_id ON run_event (tenant_id);



CREATE TABLE run_step (
	id BIGINT NOT NULL AUTO_INCREMENT, 
	run_id VARCHAR(64) NOT NULL, 
	step_no INTEGER NOT NULL, 
	step_type VARCHAR(32) NOT NULL, 
	status VARCHAR(20) NOT NULL, 
	input_summary TEXT, 
	output_summary TEXT, 
	tool_code VARCHAR(100), 
	duration_ms INTEGER NOT NULL, 
	token_input BIGINT NOT NULL, 
	token_output BIGINT NOT NULL, 
	error_code VARCHAR(100), 
	created_at DATETIME NOT NULL, 
	tenant_id VARCHAR(64) NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uk_run_step_no UNIQUE (run_id, step_no)
);

CREATE INDEX ix_run_step_run_id ON run_step (run_id);

CREATE INDEX ix_run_step_tenant_id ON run_step (tenant_id);



CREATE TABLE tool_binding (
	id BIGINT NOT NULL AUTO_INCREMENT, 
	agent_id BIGINT NOT NULL, 
	tool_code VARCHAR(100) NOT NULL, 
	enabled BOOL NOT NULL, 
	tenant_id VARCHAR(64) NOT NULL, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id)
);

CREATE INDEX ix_tool_binding_agent_id ON tool_binding (agent_id);

CREATE INDEX ix_tool_binding_tenant_id ON tool_binding (tenant_id);



CREATE TABLE tool_confirmation (
	id BIGINT NOT NULL AUTO_INCREMENT, 
	confirmation_id VARCHAR(64) NOT NULL, 
	run_id VARCHAR(64) NOT NULL, 
	conversation_id BIGINT NOT NULL, 
	tool_code VARCHAR(100) NOT NULL, 
	arguments_json JSON NOT NULL, 
	arguments_hash VARCHAR(64) NOT NULL, 
	summary TEXT NOT NULL, 
	status VARCHAR(20) NOT NULL, 
	expires_at DATETIME, 
	decided_at DATETIME, 
	tenant_id VARCHAR(64) NOT NULL, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (confirmation_id)
);

CREATE INDEX ix_tool_confirmation_run_id ON tool_confirmation (run_id);

CREATE INDEX ix_tool_confirmation_tenant_id ON tool_confirmation (tenant_id);



CREATE TABLE tool_credential (
	id BIGINT NOT NULL AUTO_INCREMENT, 
	tool_code VARCHAR(100) NOT NULL, 
	name VARCHAR(100) NOT NULL, 
	ciphertext TEXT NOT NULL, 
	key_version VARCHAR(20) NOT NULL, 
	tenant_id VARCHAR(64) NOT NULL, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id)
);

CREATE INDEX ix_tool_credential_tenant_id ON tool_credential (tenant_id);

CREATE INDEX ix_tool_credential_tool_code ON tool_credential (tool_code);



CREATE TABLE tool_definition (
	id BIGINT NOT NULL AUTO_INCREMENT, 
	tool_code VARCHAR(100) NOT NULL, 
	name VARCHAR(200) NOT NULL, 
	description TEXT, 
	source_type VARCHAR(20) NOT NULL, 
	endpoint VARCHAR(500), 
	input_schema_json JSON NOT NULL, 
	output_schema_json JSON NOT NULL, 
	auth_policy_json JSON NOT NULL, 
	timeout_ms INTEGER NOT NULL, 
	retry_policy_json JSON NOT NULL, 
	rate_limit_policy_json JSON NOT NULL, 
	write_operation BOOL NOT NULL, 
	require_confirmation BOOL NOT NULL, 
	idempotent BOOL NOT NULL, 
	audit_level VARCHAR(20) NOT NULL, 
	status VARCHAR(20) NOT NULL, 
	version_no INTEGER NOT NULL, 
	tenant_id VARCHAR(64) NOT NULL, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uk_tool_tenant_code_version UNIQUE (tenant_id, tool_code, version_no)
);

CREATE INDEX ix_tool_definition_tenant_id ON tool_definition (tenant_id);

CREATE INDEX ix_tool_definition_tool_code ON tool_definition (tool_code);



CREATE TABLE tool_idempotency_record (
	id BIGINT NOT NULL AUTO_INCREMENT, 
	tool_code VARCHAR(100) NOT NULL, 
	idempotency_key VARCHAR(128) NOT NULL, 
	arguments_hash VARCHAR(64) NOT NULL, 
	status VARCHAR(20) NOT NULL, 
	response_json JSON, 
	expires_at DATETIME, 
	tenant_id VARCHAR(64) NOT NULL, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id)
);

CREATE INDEX ix_tool_idempotency_record_idempotency_key ON tool_idempotency_record (idempotency_key);

CREATE INDEX ix_tool_idempotency_record_tenant_id ON tool_idempotency_record (tenant_id);



CREATE TABLE tool_invoke_log (
	id BIGINT NOT NULL AUTO_INCREMENT, 
	run_id VARCHAR(64), 
	tool_code VARCHAR(100) NOT NULL, 
	user_id VARCHAR(64), 
	status VARCHAR(20) NOT NULL, 
	arguments_json JSON, 
	result_summary TEXT, 
	error_code VARCHAR(100), 
	duration_ms INTEGER NOT NULL, 
	idempotency_key VARCHAR(128), 
	created_at DATETIME NOT NULL, 
	tenant_id VARCHAR(64) NOT NULL, 
	PRIMARY KEY (id)
);

CREATE INDEX ix_tool_invoke_log_idempotency_key ON tool_invoke_log (idempotency_key);

CREATE INDEX ix_tool_invoke_log_run_id ON tool_invoke_log (run_id);

CREATE INDEX ix_tool_invoke_log_tenant_id ON tool_invoke_log (tenant_id);

CREATE INDEX ix_tool_invoke_log_tool_code ON tool_invoke_log (tool_code);



CREATE TABLE user_event (
	id BIGINT NOT NULL AUTO_INCREMENT, 
	user_id VARCHAR(64) NOT NULL, 
	event_type VARCHAR(64) NOT NULL, 
	payload_json JSON NOT NULL, 
	occurred_at DATETIME NOT NULL, 
	tenant_id VARCHAR(64) NOT NULL, 
	PRIMARY KEY (id)
);

CREATE INDEX ix_user_event_tenant_id ON user_event (tenant_id);

CREATE INDEX ix_user_event_user_id ON user_event (user_id);



CREATE TABLE user_profile (
	id BIGINT NOT NULL AUTO_INCREMENT, 
	user_id VARCHAR(64) NOT NULL, 
	identity_json JSON NOT NULL, 
	style_preferences_json JSON NOT NULL, 
	tenant_id VARCHAR(64) NOT NULL, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id)
);

CREATE INDEX ix_user_profile_tenant_id ON user_profile (tenant_id);

CREATE INDEX ix_user_profile_user_id ON user_profile (user_id);



CREATE TABLE user_profile_tag (
	id BIGINT NOT NULL AUTO_INCREMENT, 
	user_id VARCHAR(64) NOT NULL, 
	tag_key VARCHAR(100) NOT NULL, 
	tag_value VARCHAR(300) NOT NULL, 
	source VARCHAR(32), 
	confidence FLOAT NOT NULL, 
	tenant_id VARCHAR(64) NOT NULL, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id)
);

CREATE INDEX ix_user_profile_tag_tenant_id ON user_profile_tag (tenant_id);

CREATE INDEX ix_user_profile_tag_user_id ON user_profile_tag (user_id);


