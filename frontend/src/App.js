/**
 * App.js - Main React Component for AI-Powered User Management System
 *
 * This is the main entry point for the frontend application. It provides:
 * - User list display with pagination
 * - AI-powered natural language search
 * - User CRUD operations (Create, Read, Update, Delete)
 * - Profile picture upload with preview
 * - Auto-generated avatar initials for users without photos
 *
 * Architecture:
 *   App Component
 *   ├── Header (title, user count)
 *   ├── Error/Success Messages
 *   ├── Add User Button
 *   ├── User Form (create/edit)
 *   ├── Search Bar (AI-powered)
 *   ├── Users Table
 *   │   ├── Avatar (uploaded or generated)
 *   │   ├── User Info (name, username, gender)
 *   │   └── Actions (edit, delete)
 *   └── Pagination Controls
 *
 * State Management:
 *   - Uses React hooks (useState, useEffect, useMemo, useCallback)
 *   - No external state library needed for this scale
 *   - Avatar cache uses memoization for performance
 */

import React, { useState, useEffect, useMemo, useCallback } from "react";
import PropTypes from "prop-types";  // Runtime type checking for React props
import axios from "axios";  // HTTP client for API requests
import "./App.css";         // Tailwind CSS styles

// ==============================================================================
// CONFIGURATION CONSTANTS
// ==============================================================================

// ==============================================================================
// CONFIGURATION
// ==============================================================================

const API_URL = process.env.REACT_APP_API_URL || "http://localhost:8000";
const MAX_FILE_SIZE = 5 * 1024 * 1024; // 5MB
// Use Set for O(1) lookup performance when checking file types (better than array includes())
const ALLOWED_FILE_TYPES = new Set(['image/jpeg', 'image/png', 'image/gif', 'image/webp']);
const USERS_PER_PAGE = 50;

// Gender badge colors
const GENDER_COLORS = {
    Male: "bg-blue-500",
    Female: "bg-pink-500",
    Other: "bg-purple-500"
};

// Avatar background colors by gender
const AVATAR_COLORS = {
    Male: "#3B82F6",
    Female: "#EC4899",
    Other: "#8B5CF6"
};

// ==============================================================================
// HELPER FUNCTIONS
// ==============================================================================

/**
 * Validate file for upload.
 * @returns {string|null} Error message or null if valid
 */
function validateFile(file) {
    if (!ALLOWED_FILE_TYPES.has(file.type)) {
        return "Invalid file type. Please upload JPEG, PNG, GIF, or WebP";
    }
    if (file.size > MAX_FILE_SIZE) {
        return "File too large. Maximum size is 5MB";
    }
    return null;
}

/**
 * Get initials from a full name.
 */
function getInitials(fullName) {
    const names = fullName.trim().split(" ");
    if (names.length >= 2) {
        return `${names[0][0]}${names[names.length - 1][0]}`.toUpperCase();
    }
    return names[0].substring(0, 2).toUpperCase();
}

/**
 * Create initial form data state.
 */
function createEmptyFormData() {
    return {
        full_name: "",
        username: "",
        password: "",
        gender: "",
        profile_pic: null,
    };
}

// ==============================================================================
// SUB-COMPONENTS
// ==============================================================================

/**
 * Alert message component for errors and success notifications.
 */
function AlertMessage({ type, message }) {
    const styles = {
        error: "bg-red-50 border-l-4 border-red-500 text-red-700",
        success: "bg-green-50 border-l-4 border-green-500 text-green-700"
    };
    const icons = { error: "Warning", success: "Success" };
    const emoji = type === "error" ? "⚠️" : "✓";

    return (
        <div className={`${styles[type]} p-4 mb-4 rounded-lg animate-slideDown`}>
            <p className="font-medium">{emoji} {icons[type]}</p>
            <p className="text-sm mt-1">{message}</p>
        </div>
    );
}

AlertMessage.propTypes = {
    type: PropTypes.oneOf(['error', 'success']).isRequired,
    message: PropTypes.string.isRequired
};

/**
 * Search info display showing filters, warnings, and result counts.
 */
function SearchInfo({ searchInfo, usersPerPage }) {
    if (searchInfo === null || searchInfo === undefined) return null;

    const userLabel = searchInfo.total === 1 ? 'user' : 'users';
    const showPageInfo = searchInfo.total > usersPerPage;

    return (
        <div className="mt-2 space-y-1">
            <div className="text-sm text-gray-600">
                Found {searchInfo.total.toLocaleString()} matching {userLabel}
                {showPageInfo && ` (showing ${searchInfo.count} per page)`}
            </div>

            {searchInfo.filters_applied && (
                <div className="text-xs text-blue-600">
                    Filters: {Object.entries(searchInfo.filters_applied)
                        .map(([key, val]) => `${key.replaceAll('_', ' ')}: ${val}`)
                        .join(' | ')}
                </div>
            )}

            {searchInfo.parse_warnings && searchInfo.parse_warnings.length > 0 && (
                <div className="text-xs text-amber-600 bg-amber-50 p-2 rounded">
                    {searchInfo.parse_warnings.map((warning) => (
                        <div key={warning}>Note: {warning}</div>
                    ))}
                </div>
            )}

            {searchInfo.query_understood === false && (
                <div className="text-xs text-red-600 bg-red-50 p-2 rounded">
                    Your query couldn&apos;t be fully understood. Try: &quot;female users&quot;, &quot;users named John&quot;, &quot;users starting with A&quot;, or &quot;users with odd letters in name&quot;
                </div>
            )}
        </div>
    );
}

SearchInfo.propTypes = {
    searchInfo: PropTypes.shape({
        count: PropTypes.number,
        total: PropTypes.number,
        message: PropTypes.string,
        has_more: PropTypes.bool,
        query_understood: PropTypes.bool,
        parse_warnings: PropTypes.arrayOf(PropTypes.string),
        filters_applied: PropTypes.object
    }),
    usersPerPage: PropTypes.number.isRequired
};

/**
 * Gender badge component.
 */
function GenderBadge({ gender }) {
    const colorClass = GENDER_COLORS[gender] || GENDER_COLORS.Other;
    return (
        <span className={`px-3 py-1 rounded-full text-white text-sm ${colorClass}`}>
            {gender}
        </span>
    );
}

GenderBadge.propTypes = {
    gender: PropTypes.oneOf(['Male', 'Female', 'Other']).isRequired
};

/**
 * User table row component.
 */
function UserRow({ user, avatarSrc, onEdit, onDelete }) {
    return (
        <tr className="border-b hover:bg-gray-50">
            <td className="px-4 py-3">
                <img src={avatarSrc} alt={user.full_name} className="w-12 h-12 rounded-full" />
            </td>
            <td className="px-4 py-3 font-medium">{user.full_name}</td>
            <td className="px-4 py-3 text-gray-600">@{user.username}</td>
            <td className="px-4 py-3">
                <GenderBadge gender={user.gender} />
            </td>
            <td className="px-4 py-3">
                <div className="flex gap-2">
                    <button
                        onClick={() => onEdit(user)}
                        className="bg-yellow-500 hover:bg-yellow-600 text-white px-4 py-2 rounded-lg text-sm"
                    >
                        Edit
                    </button>
                    <button
                        onClick={() => onDelete(user)}
                        className="bg-red-600 hover:bg-red-700 text-white px-4 py-2 rounded-lg text-sm"
                    >
                        Delete
                    </button>
                </div>
            </td>
        </tr>
    );
}

UserRow.propTypes = {
    user: PropTypes.shape({
        id: PropTypes.number.isRequired,
        full_name: PropTypes.string.isRequired,
        username: PropTypes.string.isRequired,
        gender: PropTypes.oneOf(['Male', 'Female', 'Other']).isRequired,
        profile_pic: PropTypes.string
    }).isRequired,
    avatarSrc: PropTypes.string.isRequired,
    onEdit: PropTypes.func.isRequired,
    onDelete: PropTypes.func.isRequired
};

/**
 * Pagination Controls Component
 *
 * Renders navigation buttons for paginated results:
 * - First page button (⟨⟨)
 * - Previous page button (⟨ Prev)
 * - Current page indicator
 * - Next page button (Next ⟩)
 * - Last page button (⟩⟩)
 *
 * Also shows "Showing X to Y of Z users" info.
 */
function PaginationControls({
    currentPage,
    totalPages,
    totalUsers,
    usersPerPage,
    hasPrevPage,
    hasNextPage,
    isLoading,
    onGoToPage
}) {
    const startItem = ((currentPage - 1) * usersPerPage) + 1;
    const endItem = Math.min(currentPage * usersPerPage, totalUsers);

    return (
        <div className="mt-6 flex items-center justify-between border-t pt-4">
            <div className="text-sm text-gray-600">
                Showing {startItem} to {endItem} of {totalUsers.toLocaleString()} users
            </div>

            <div className="flex gap-2">
                <button
                    onClick={() => onGoToPage(1)}
                    disabled={!hasPrevPage || isLoading}
                    className="px-3 py-2 border rounded-lg hover:bg-gray-100 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                >
                    ⟨⟨
                </button>
                <button
                    onClick={() => onGoToPage(currentPage - 1)}
                    disabled={!hasPrevPage || isLoading}
                    className="px-3 py-2 border rounded-lg hover:bg-gray-100 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                >
                    ⟨ Prev
                </button>

                <div className="px-4 py-2 border rounded-lg bg-blue-50 text-blue-700 font-medium">
                    Page {currentPage} of {totalPages.toLocaleString()}
                </div>

                <button
                    onClick={() => onGoToPage(currentPage + 1)}
                    disabled={!hasNextPage || isLoading}
                    className="px-3 py-2 border rounded-lg hover:bg-gray-100 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                >
                    Next ⟩
                </button>
                <button
                    onClick={() => onGoToPage(totalPages)}
                    disabled={!hasNextPage || isLoading}
                    className="px-3 py-2 border rounded-lg hover:bg-gray-100 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                >
                    ⟩⟩
                </button>
            </div>

            <div className="text-sm text-gray-600">
                {totalPages.toLocaleString()} pages
            </div>
        </div>
    );
}

PaginationControls.propTypes = {
    currentPage: PropTypes.number.isRequired,
    totalPages: PropTypes.number.isRequired,
    totalUsers: PropTypes.number.isRequired,
    usersPerPage: PropTypes.number.isRequired,
    hasPrevPage: PropTypes.bool.isRequired,
    hasNextPage: PropTypes.bool.isRequired,
    isLoading: PropTypes.bool.isRequired,
    onGoToPage: PropTypes.func.isRequired
};

// ==============================================================================
// MAIN APPLICATION COMPONENT
// ==============================================================================

function App() {
    // ==========================================================================
    // STATE MANAGEMENT
    // All state is managed using React hooks. State is organized by category
    // for easier maintenance and understanding.
    // ==========================================================================

    // --------------------------------------------------------------------------
    // User Data State
    // Stores the current page of users and pagination metadata
    // --------------------------------------------------------------------------
    const [users, setUsers] = useState([]);           // Current page of user objects
    const [totalUsers, setTotalUsers] = useState(0);  // Total user count (for pagination)
    const [currentPage, setCurrentPage] = useState(1); // Current page number (1-indexed)

    // --------------------------------------------------------------------------
    // UI State
    // Controls visibility of forms and modals
    // --------------------------------------------------------------------------
    const [showForm, setShowForm] = useState(false);   // Show/hide user form
    const [editingUser, setEditingUser] = useState(null); // User being edited (null = create mode)

    // --------------------------------------------------------------------------
    // Form State
    // Stores form input values for create/edit operations
    // --------------------------------------------------------------------------
    const [formData, setFormData] = useState({
        full_name: "",      // User's full name (2-255 chars)
        username: "",       // Unique username (3-50 chars, alphanumeric + underscore)
        password: "",       // Password (8+ chars, or empty when editing to keep current)
        gender: "",         // Gender selection: Male, Female, or Other
        profile_pic: null,  // File object for profile picture upload
    });
    const [previewImage, setPreviewImage] = useState(null); // Base64 preview of selected image

    // --------------------------------------------------------------------------
    // Search State
    // Manages AI-powered search functionality
    // --------------------------------------------------------------------------
    const [searchQuery, setSearchQuery] = useState("");        // Input field value
    const [activeSearchQuery, setActiveSearchQuery] = useState(""); // Query that was executed
    const [isSearching, setIsSearching] = useState(false);     // Search loading state
    const [searchInfo, setSearchInfo] = useState(null);        // Search metadata (filters, warnings)

    // --------------------------------------------------------------------------
    // Feedback State
    // Error and success messages for user feedback
    // --------------------------------------------------------------------------
    const [error, setError] = useState(null);     // Error message (red banner)
    const [success, setSuccess] = useState(null); // Success message (green banner)

    // --------------------------------------------------------------------------
    // Loading State
    // General loading indicator for API operations
    // --------------------------------------------------------------------------
    const [isLoading, setIsLoading] = useState(false);

    // --------------------------------------------------------------------------
    // Performance Optimization
    // Memoized avatar cache to prevent regenerating avatars on every render
    // --------------------------------------------------------------------------
    const avatarCache = useMemo(() => new Map(), []);

    // ==============================================================================
    // COMPUTED VALUES
    // These values are derived from state and recalculated on each render.
    // ==============================================================================

    /** Total number of pages based on user count and page size */
    const totalPages = Math.ceil(totalUsers / USERS_PER_PAGE);

    /** Whether there are more pages after the current one */
    const hasNextPage = currentPage < totalPages;

    /** Whether there are pages before the current one */
    const hasPrevPage = currentPage > 1;

    // ==============================================================================
    // EFFECTS (Side Effects)
    // useEffect hooks that run in response to state changes.
    // ==============================================================================

    /**
     * Effect: Fetch users when page changes
     *
     * This effect handles pagination for both normal browsing and search results.
     * When currentPage changes, it determines whether to fetch normal users
     * or search results based on whether there's an active search query.
     *
     * Note: We intentionally only depend on currentPage, not activeSearchQuery.
     * Adding activeSearchQuery would cause double-fetching when search is triggered.
     */
    useEffect(() => {
        if (activeSearchQuery) {
            // User has an active search - paginate search results
            performSearch(activeSearchQuery, currentPage);
        } else {
            // No search active - show normal user list
            fetchUsers(currentPage);
        }
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [currentPage]);

    /**
     * Effect: Auto-dismiss success messages after 5 seconds
     *
     * This provides better UX by automatically clearing success messages
     * so users don't have to manually dismiss them.
     */
    useEffect(() => {
        if (success) {
            const timer = setTimeout(() => setSuccess(null), 5000);
            return () => clearTimeout(timer); // Cleanup on unmount or re-run
        }
    }, [success]);

    // ==============================================================================
    // API FUNCTIONS
    // Functions that communicate with the backend API.
    // ==============================================================================

    /**
     * Fetch users from the backend with pagination.
     *
     * @param {number} page - Page number to fetch (1-indexed)
     *
     * Response format from backend:
     * {
     *   users: [...],    // Array of user objects
     *   total: 1000,     // Total user count
     *   skip: 0,         // Records skipped
     *   limit: 50,       // Page size
     *   has_more: true   // More pages available
     * }
     */
    const fetchUsers = async (page = 1) => {
        try {
            setError(null);
            setIsLoading(true);

            const skip = (page - 1) * USERS_PER_PAGE;
            const res = await axios.get(`${API_URL}/users/?skip=${skip}&limit=${USERS_PER_PAGE}`);

            // Handle both response formats
            if (res.data.users) {
                // New format with pagination data
                setUsers(res.data.users);
                setTotalUsers(res.data.total);
            } else {
                // Old format (array)
                setUsers(res.data);
                setTotalUsers(res.data.length);
            }

            setSearchInfo(null); // Clear any previous search metadata
        } catch (err) {
            console.error("Error fetching users:", err);
            // Extract error message from API response, or use generic message
            setError(err.response?.data?.detail || "Failed to load users");
        } finally {
            setIsLoading(false);
        }
    };

    /**
     * Perform AI-powered search for users.
     *
     * This sends a natural language query to the backend's /ai/search endpoint,
     * which uses the Ollama LLM to parse the query and filter users.
     *
     * @param {string} query - Natural language search query (e.g., "female users named Taylor")
     * @param {number} page - Page number for pagination (1-indexed)
     *
     * Example queries:
     * - "female users with Taylor in their name"
     * - "users starting with J"
     * - "male users"
     * - "users with odd number of letters in name"
     */
    const performSearch = async (query, page = 1) => {
        try {
            setError(null);
            setIsSearching(true);

            const skip = (page - 1) * USERS_PER_PAGE;
            const res = await axios.get(`${API_URL}/ai/search`, {
                params: {
                    query,
                    skip,
                    limit: USERS_PER_PAGE
                }
            });

            setUsers(res.data.results || []);
            setTotalUsers(res.data.total || 0);
            setSearchInfo({
                count: res.data.count || 0,
                total: res.data.total || 0,
                message: res.data.message,
                has_more: res.data.has_more,
                query_understood: res.data.query_understood,
                parse_warnings: res.data.parse_warnings || [],
                filters_applied: res.data.filters_applied
            });

        } catch (err) {
            console.error("Error searching:", err);
            setError(err.response?.data?.detail || "Search failed");
        } finally {
            setIsSearching(false);
        }
    };

    /**
     * Handle search form submission.
     *
     * If the search query is empty, clears the search and shows all users.
     * Otherwise, executes the AI search and resets to page 1.
     *
     * @param {Event} e - Form submit event
     */
    const handleSearch = (e) => {
        e.preventDefault(); // Prevent form submission from reloading page
        if (searchQuery.trim() === "") {
            // Empty query - clear search and show all users
            setActiveSearchQuery("");
            setSearchInfo(null);
            setCurrentPage(1);
            fetchUsers(1);
        } else {
            // Execute AI search - always start from page 1
            setActiveSearchQuery(searchQuery);
            setCurrentPage(1);
            performSearch(searchQuery, 1);
        }
    };

    /**
     * Handle Enter key press in search input.
     * Triggers search without needing to click the button.
     */
    const handleSearchKeyPress = (e) => {
        if (e.key === 'Enter') {
            handleSearch(e);
        }
    };

    /**
     * Handle user form submission (create or update).
     *
     * This function:
     * 1. Builds FormData with user fields and optional profile picture
     * 2. Sends POST (create) or PUT (update) request to backend
     * 3. Refreshes the user list on success
     * 4. Displays appropriate success/error messages
     *
     * @param {Event} e - Form submit event
     */
    const handleSubmit = async (e) => {
        e.preventDefault();
        setError(null);
        setSuccess(null);

        try {
            setIsLoading(true);

            const data = new FormData();
            data.append("full_name", formData.full_name);
            data.append("username", formData.username);
            if (formData.password) {
                data.append("password", formData.password);
            }
            data.append("gender", formData.gender);
            if (formData.profile_pic) {
                data.append("profile_pic", formData.profile_pic);
            }

            if (editingUser) {
                await axios.put(`${API_URL}/users/${editingUser.id}`, data, {
                    headers: { "Content-Type": "multipart/form-data" },
                });
                setSuccess("User updated successfully!");
            } else {
                await axios.post(`${API_URL}/users/`, data, {
                    headers: { "Content-Type": "multipart/form-data" },
                });
                setSuccess("User created successfully!");
            }

            // Refresh current page
            fetchUsers(currentPage);
            cancelForm();
        } catch (err) {
            console.error("Error submitting form:", err);
            setError(err.response?.data?.detail || "Operation failed");
        } finally {
            setIsLoading(false);
        }
    };

    /**
     * Handle user deletion.
     *
     * Prompts for confirmation, then sends DELETE request to backend.
     * The backend also removes the user's profile picture from storage.
     *
     * @param {Object} user - User object to delete
     */
    const handleDelete = async (user) => {
        // eslint-disable-next-line no-restricted-globals
        const confirmed = confirm(`Delete user "${user.username}"?`);
        if (!confirmed) {
            return;
        }

        try {
            setError(null);
            setIsLoading(true);

            await axios.delete(`${API_URL}/users/${user.id}`);
            setSuccess("User deleted successfully!");

            // Refresh current page
            fetchUsers(currentPage);
        } catch (err) {
            console.error("Error deleting user:", err);
            setError(err.response?.data?.detail || "Failed to delete user");
        } finally {
            setIsLoading(false);
        }
    };

    /**
     * Handle clicking the Edit button on a user.
     *
     * Populates the form with the user's current data and switches
     * the form to edit mode. Password field is left empty - user
     * only needs to fill it if they want to change the password.
     *
     * @param {Object} user - User object to edit
     */
    const handleEdit = (user) => {
        setEditingUser(user);  // Store reference to user being edited
        setFormData({
            full_name: user.full_name,
            username: user.username,
            password: "",  // Empty - user only fills if changing password
            gender: user.gender,
            profile_pic: null,  // Clear file input - user re-selects if changing
        });
        // Show current profile picture as preview (from server)
        setPreviewImage(user.profile_pic ? `${API_URL}/${user.profile_pic}` : null);
        setShowForm(true);
        setError(null);
    };

    /**
     * Cancel and reset the user form.
     */
    const cancelForm = () => {
        setShowForm(false);
        setEditingUser(null);
        setFormData(createEmptyFormData());
        setPreviewImage(null);
        setError(null);
    };

    /**
     * Handle profile picture file selection with validation and preview.
     */
    const handleFileChange = (e) => {
        const file = e.target.files[0];
        if (!file) return;

        const validationError = validateFile(file);
        if (validationError) {
            setError(validationError);
            return;
        }

        setFormData({ ...formData, profile_pic: file });

        const reader = new FileReader();
        reader.onloadend = () => setPreviewImage(reader.result);
        reader.readAsDataURL(file);
    };

    // ==============================================================================
    // AVATAR GENERATION (Memoized)
    // Generates initials-based avatars for users without profile pictures.
    // Uses HTML5 Canvas API and caches results for performance.
    // ==============================================================================

    /**
     * Generate an initials-based avatar image for a user.
     * Results are cached for performance.
     */
    const generateInitialsImage = useCallback((fullName, gender) => {
        const cacheKey = `${fullName}-${gender}`;

        if (avatarCache.has(cacheKey)) {
            return avatarCache.get(cacheKey);
        }

        const canvas = document.createElement("canvas");
        canvas.width = 100;
        canvas.height = 100;
        const ctx = canvas.getContext("2d");

        // Draw background
        ctx.fillStyle = AVATAR_COLORS[gender] || AVATAR_COLORS.Other;
        ctx.fillRect(0, 0, 100, 100);

        // Draw initials
        ctx.fillStyle = "#FFFFFF";
        ctx.font = "bold 40px Arial";
        ctx.textAlign = "center";
        ctx.textBaseline = "middle";
        ctx.fillText(getInitials(fullName), 50, 50);

        const dataURL = canvas.toDataURL();
        avatarCache.set(cacheKey, dataURL);

        return dataURL;
    }, [avatarCache]);

    // ==============================================================================
    // PAGINATION CONTROLS
    // Handles navigation between pages of user results.
    // ==============================================================================

    /**
     * Navigate to a specific page number.
     *
     * Validates the page is within bounds before changing.
     * Scrolls to top of page for better UX after navigation.
     *
     * @param {number} page - Page number to navigate to (1-indexed)
     */
    const goToPage = (page) => {
        if (page >= 1 && page <= totalPages) {
            setCurrentPage(page);
            window.scrollTo({ top: 0, behavior: 'smooth' });
        }
    };

    // ==============================================================================
    // RENDER
    // ==============================================================================

    return (
        <div className="min-h-screen bg-gradient-to-br from-blue-50 via-purple-50 to-pink-50">
            <div className="container mx-auto px-4 py-8 max-w-7xl">
                {/* Header */}
                <div className="text-center mb-8 animate-fadeIn">
                    <h1 className="text-5xl font-extrabold text-transparent bg-clip-text bg-gradient-to-r from-blue-600 to-purple-600 mb-2">
                        🚀 AI-Powered User Management
                    </h1>
                    <p className="text-gray-600 text-lg">
                        Smart search with natural language • {totalUsers.toLocaleString()} total users
                    </p>
                </div>

                {/* Error/Success Messages */}
                {error && <AlertMessage type="error" message={error} />}
                {success && <AlertMessage type="success" message={success} />}

                {/* Add User Button */}
                {!showForm && (
                    <button
                        onClick={() => setShowForm(true)}
                        disabled={isLoading}
                        className="mb-6 bg-blue-600 hover:bg-blue-700 text-white font-semibold py-3 px-6 rounded-lg shadow-md transition-all disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2"
                    >
                        <span className="text-xl font-bold">+</span>
                        <span>Add New User</span>
                    </button>
                )}

                {/* User Form */}
                {showForm && (
                    <form onSubmit={handleSubmit} className="bg-white p-6 rounded-lg shadow-md mb-6 animate-fadeIn">
                        <h2 className="text-2xl font-bold mb-4 text-gray-800">
                            {editingUser ? "Edit User" : "Create New User"}
                        </h2>
                        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                            <input
                                type="text"
                                placeholder="Full Name"
                                value={formData.full_name}
                                onChange={(e) => setFormData({ ...formData, full_name: e.target.value })}
                                required
                                className="w-full px-4 py-2 border rounded-lg"
                            />
                            <input
                                type="text"
                                placeholder="Username"
                                value={formData.username}
                                onChange={(e) => setFormData({ ...formData, username: e.target.value })}
                                required
                                className="w-full px-4 py-2 border rounded-lg"
                            />
                            <input
                                type="password"
                                placeholder={editingUser ? "New Password (leave blank to keep)" : "Password"}
                                value={formData.password}
                                onChange={(e) => setFormData({ ...formData, password: e.target.value })}
                                required={!editingUser}
                                className="w-full px-4 py-2 border rounded-lg"
                            />
                            <select
                                value={formData.gender}
                                onChange={(e) => setFormData({ ...formData, gender: e.target.value })}
                                required
                                className="w-full px-4 py-2 border rounded-lg"
                            >
                                <option value="">Select Gender</option>
                                <option value="Male">Male</option>
                                <option value="Female">Female</option>
                                <option value="Other">Other</option>
                            </select>
                            <div className="md:col-span-2">
                                <input
                                    type="file"
                                    accept="image/jpeg,image/png,image/gif,image/webp"
                                    onChange={handleFileChange}
                                    className="w-full"
                                />
                                {previewImage && (
                                    <img src={previewImage} alt="Preview" className="w-20 h-20 mt-2 rounded-full" />
                                )}
                            </div>
                        </div>
                        <div className="mt-6 flex gap-4">
                            <button
                                type="submit"
                                disabled={isLoading}
                                className="bg-green-600 hover:bg-green-700 text-white py-2 px-6 rounded-lg"
                            >
                                {/* Extract nested ternary for readability (SonarQube S3358) */}
                                {isLoading && "Saving..."}
                                {!isLoading && editingUser && "Update User"}
                                {!isLoading && !editingUser && "Create User"}
                            </button>
                            <button
                                type="button"
                                onClick={cancelForm}
                                className="bg-gray-500 hover:bg-gray-600 text-white py-2 px-6 rounded-lg"
                            >
                                Cancel
                            </button>
                        </div>
                    </form>
                )}

                {/* Search Bar */}
                <div className="bg-white p-4 rounded-lg shadow-md mb-6">
                    <div className="relative flex gap-2">
                        <input
                            type="text"
                            value={searchQuery}
                            onChange={(e) => setSearchQuery(e.target.value)}
                            onKeyPress={handleSearchKeyPress}
                            placeholder='🔍 Smart search... Try "female users" or "users named Taylor" (Press Enter to search)'
                            className="flex-1 px-4 py-3 border rounded-lg"
                        />
                        <button
                            onClick={handleSearch}
                            disabled={isSearching}
                            className="px-6 py-3 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:bg-gray-500 disabled:cursor-not-allowed transition"
                        >
                            {isSearching ? "Searching..." : "Search"}
                        </button>
                        {activeSearchQuery && (
                            <button
                                onClick={() => {
                                    setSearchQuery("");
                                    setActiveSearchQuery("");
                                    setSearchInfo(null);
                                    setCurrentPage(1);
                                    fetchUsers(1);
                                }}
                                className="px-4 py-3 bg-gray-500 text-white rounded-lg hover:bg-gray-600 transition"
                                title="Clear search and show all users"
                            >
                                Clear
                            </button>
                        )}
                        {isSearching && (
                            <div className="absolute right-24 top-1/2 transform -translate-y-1/2">
                                <div className="animate-spin rounded-full h-5 w-5 border-b-2 border-blue-600"></div>
                            </div>
                        )}
                    </div>
                    <SearchInfo searchInfo={searchInfo} usersPerPage={USERS_PER_PAGE} />
                </div>

                {/* Users Table */}
                <div className="bg-white p-6 rounded-lg shadow-md">
                    <h2 className="text-2xl font-bold mb-4 text-gray-800">
                        {activeSearchQuery ? (
                            <>Search Results <span className="text-base font-normal text-gray-500">for "{activeSearchQuery}"</span></>
                        ) : (
                            <>Users</>
                        )}
                        <span className="text-base font-normal text-gray-500 ml-2">
                            ({users.length} on this page{totalUsers > 0 && `, ${totalUsers.toLocaleString()} total`})
                        </span>
                    </h2>

                    {/* Loading state - only show when loading AND no cached users */}
                    {isLoading && users.length === 0 && (
                        <div className="text-center py-8">
                            <div className="inline-block animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600"></div>
                            <p className="text-gray-600 mt-2">Loading...</p>
                        </div>
                    )}

                    {/* Users table - show when we have users (even while loading more) */}
                    {users.length > 0 && (
                        <>
                            <div className="overflow-x-auto">
                                <table className="min-w-full">
                                    <thead className="border-b bg-gray-50">
                                    <tr>
                                        <th className="px-4 py-3 text-left">Avatar</th>
                                        <th className="px-4 py-3 text-left">Full Name</th>
                                        <th className="px-4 py-3 text-left">Username</th>
                                        <th className="px-4 py-3 text-left">Gender</th>
                                        <th className="px-4 py-3 text-left">Actions</th>
                                    </tr>
                                    </thead>
                                    <tbody>
                                    {users.map((user) => {
                                        const avatarSrc = user.profile_pic
                                            ? `${API_URL}/${user.profile_pic}`
                                            : generateInitialsImage(user.full_name, user.gender);
                                        return (
                                            <UserRow
                                                key={user.id}
                                                user={user}
                                                avatarSrc={avatarSrc}
                                                onEdit={handleEdit}
                                                onDelete={handleDelete}
                                            />
                                        );
                                    })}
                                    </tbody>
                                </table>
                            </div>

                            {/* Pagination Controls - show for both normal browse and search */}
                            {totalPages > 1 && (
                                <PaginationControls
                                    currentPage={currentPage}
                                    totalPages={totalPages}
                                    totalUsers={totalUsers}
                                    usersPerPage={USERS_PER_PAGE}
                                    hasPrevPage={hasPrevPage}
                                    hasNextPage={hasNextPage}
                                    isLoading={isLoading}
                                    onGoToPage={goToPage}
                                />
                            )}
                        </>
                    )}

                    {/* Empty state - only show when not loading AND no users */}
                    {!isLoading && users.length === 0 && (
                        <div className="text-center py-8 text-gray-500">
                            <p className="text-lg">No users found</p>
                        </div>
                    )}
                </div>
            </div>
        </div>
    );
}

export default App;