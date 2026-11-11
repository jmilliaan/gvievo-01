# /amr/line/order_state (station call plan 4.4): latched, on change and at 1 Hz. The job's side of the
# station contract; the MQTT bridge builds `state` from it. Consumers drop other generations.
std_msgs/Header header
uint32 generation
string order_id        # current or last accepted order. "" in a new process
string machine         # "MRU3", or a pair "MRU1+MRU3" (the closer first)
bool active
bool departed
string att_status      # WAITING, RUNNING, FINISHED, FAILED, or ""
string mw_status
string me_status       # one machine: ME. A pair (a+b, closer first): mw = MW-a, me = ME-a
string mw2_status      # a pair's MW-b; "" for one machine (2026-11-11, contract v1.2 proposal)
string me2_status      # a pair's ME-b; "" for one machine
string last_node_id
uint16 last_node_seq
bool driving           # wheel command non-zero this tick, RUNNING only
uint8 trolley          # TrolleyState.state as fresh on this tick, UNKNOWN when stale
uint8 rear_field       # TrolleyState.rear_field, likewise
string[] not_ready     # contract section 8 reasons, in that table's order
uint32 refusal_seq     # latest job-level refusal
string refusal_type
string refusal_order_id
string refusal_reason
string cancelled_reason
string cancelled_text
string aborted_reason
string aborted_text
string start_refused_node
string start_refused_reason
uint32 cancel_seq      # latest cancelOrder result
string cancel_action_id
string cancel_status
string cancel_error
