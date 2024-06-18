package apply

// IntValueChanges stores changes in integer values (NumPartitions & ReplicationFactor)
// if a topic is being created then Updated == Current
type IntValueChanges struct {
	Current int `json:"current"`
	Updated int `json:"updated"`
}

// ConfigEntryChanges holds configs to be updated, as well as their current and updated values
// if a topic is being created then Updated == Current
type ConfigEntryChanges struct {
	Name    string `json:"name"`
	Current string `json:"current"`
	Updated string `json:"updated"`
}

// ReplicaAssignmentChanges stores replica reassignment
// if a topic is being created then UpdatedReplicas == CurrentReplicas
// TODO: update Changes to actually support replica reassignment
type ReplicaAssignmentChanges struct {
	Partition       int   `json:"partition"`
	CurrentReplicas []int `json:"currentReplicas"`
	UpdatedReplicas []int `json:"updatedReplicas"`
}

// enum for possible Action values in ChangesTracker
type ActionEnum string

const (
	ActionEnumCreate ActionEnum = "create"
	ActionEnumUpdate ActionEnum = "update"
)

// ChangesTracker stores what's changed in a topic during an apply run
// to eventually be printed to stdout as a JSON blob in subcmd/apply.go
type ChangesTracker struct {
	// Topic name
	Topic string `json:"topic"`

	// NumPartitions created. -1 indicates unset.
	NumPartitions IntValueChanges `json:"numPartitions"`

	// ReplicationFactor for the topic. -1 indicates unset.
	ReplicationFactor IntValueChanges `json:"replicationFactor"`

	// ReplicaAssignments among kafka brokers for this topic partitions. If this
	// is set num_partitions and replication_factor must be unset.
	ReplicaAssignments []ReplicaAssignmentChanges `json:"replicaAssignments"`

	// ConfigEntries holds topic level configuration for topic to be set.
	ConfigEntries []ConfigEntryChanges `json:"configEntries"`

	// MissingKeys stores configs which are set in the cluster but not in the topicctl config
	MissingKeys []string `json:"missingKeys"`

	// Action records whether this is a topic being created or updated
	Action ActionEnum `json:"action"`
}
