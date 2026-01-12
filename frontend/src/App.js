import React, { useState, useEffect, useMemo, useCallback } from "react";
import axios from "axios";
import "./App.css";

// ==============================================================================
// CONFIGURATION
// ==============================================================================

const API_URL = process.env.REACT_APP_API_URL || "http://localhost:8000";
const MAX_FILE_SIZE = 5 * 1024 * 1024; // 5MB
const ALLOWED_FILE_TYPES = ['image/jpeg', 'image/png', 'image/gif', 'image/webp'];
const USERS_PER_PAGE = 50; // Show 50 users per page

// ==============================================================================
// MAIN COMPONENT
// ==============================================================================

function App() {
    // ==============================================================================
    // STATE MANAGEMENT
    // ==============================================================================

    // User data with pagination
    const [users, setUsers] = useState([]);
    const [totalUsers, setTotalUsers] = useState(0);
    const [currentPage, setCurrentPage] = useState(1);

    // UI state
    const [showForm, setShowForm] = useState(false);
    const [editingUser, setEditingUser] = useState(null);

    // Form data
    const [formData, setFormData] = useState({
        full_name: "",
        username: "",
        password: "",
        gender: "",
        profile_pic: null,
    });
    const [previewImage, setPreviewImage] = useState(null);

    // Search state
    const [searchQuery, setSearchQuery] = useState("");
    const [isSearching, setIsSearching] = useState(false);
    const [searchInfo, setSearchInfo] = useState(null);

    // Error handling
    const [error, setError] = useState(null);
    const [success, setSuccess] = useState(null);

    // Loading states
    const [isLoading, setIsLoading] = useState(false);

    // Avatar cache (memoized)
    const avatarCache = useMemo(() => new Map(), []);

    // ==============================================================================
    // COMPUTED VALUES
    // ==============================================================================

    const totalPages = Math.ceil(totalUsers / USERS_PER_PAGE);
    const hasNextPage = currentPage < totalPages;
    const hasPrevPage = currentPage > 1;

    // ==============================================================================
    // EFFECTS
    // ==============================================================================

    // Fetch users when page changes
    // eslint-disable-next-line react-hooks/exhaustive-deps
    useEffect(() => {
        if (!searchQuery) {
            fetchUsers(currentPage);
        }
    }, [currentPage]);

    // Auto-dismiss success messages
    useEffect(() => {
        if (success) {
            const timer = setTimeout(() => setSuccess(null), 5000);
            return () => clearTimeout(timer);
        }
    }, [success]);

    // ==============================================================================
    // API FUNCTIONS
    // ==============================================================================

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

            setSearchInfo(null);
        } catch (err) {
            console.error("Error fetching users:", err);
            setError(err.response?.data?.detail || "Failed to load users");
        } finally {
            setIsLoading(false);
        }
    };

    const performSearch = async (query) => {
        try {
            setError(null);
            setIsSearching(true);
            const res = await axios.get(`${API_URL}/ai/search`, {
                params: { query, batch_size: 200 }
            });

            setUsers(res.data.results || []);
            setSearchInfo({
                count: res.data.count || 0,
                message: res.data.message,
                truncated: res.data.truncated
            });

            // Reset pagination when searching
            setCurrentPage(1);
            setTotalUsers(res.data.count || 0);
        } catch (err) {
            console.error("Error searching:", err);
            setError(err.response?.data?.detail || "Search failed");
        } finally {
            setIsSearching(false);
        }
    };

    const handleSearch = (e) => {
        e.preventDefault(); // Prevent form submission
        if (searchQuery.trim() === "") {
            // Clear search - fetch all users
            setSearchInfo(null);
            setCurrentPage(1);
            fetchUsers(1);
        } else {
            // Perform search
            performSearch(searchQuery);
        }
    };

    const handleSearchKeyPress = (e) => {
        if (e.key === 'Enter') {
            handleSearch(e);
        }
    };

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

    const handleDelete = async (user) => {
        if (!window.confirm(`Delete user "${user.username}"?`)) {
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

    const handleEdit = (user) => {
        setEditingUser(user);
        setFormData({
            full_name: user.full_name,
            username: user.username,
            password: "",
            gender: user.gender,
            profile_pic: null,
        });
        setPreviewImage(user.profile_pic ? `${API_URL}/${user.profile_pic}` : null);
        setShowForm(true);
        setError(null);
    };

    const cancelForm = () => {
        setShowForm(false);
        setEditingUser(null);
        setFormData({
            full_name: "",
            username: "",
            password: "",
            gender: "",
            profile_pic: null,
        });
        setPreviewImage(null);
        setError(null);
    };

    const handleFileChange = (e) => {
        const file = e.target.files[0];
        if (!file) return;

        // Validate file type
        if (!ALLOWED_FILE_TYPES.includes(file.type)) {
            setError("Invalid file type. Please upload JPEG, PNG, GIF, or WebP");
            return;
        }

        // Validate file size
        if (file.size > MAX_FILE_SIZE) {
            setError("File too large. Maximum size is 5MB");
            return;
        }

        setFormData({ ...formData, profile_pic: file });

        // Preview
        const reader = new FileReader();
        reader.onloadend = () => setPreviewImage(reader.result);
        reader.readAsDataURL(file);
    };

    // ==============================================================================
    // AVATAR GENERATION (Memoized)
    // ==============================================================================

    const generateInitialsImage = useCallback((fullName, gender) => {
        const cacheKey = `${fullName}-${gender}`;

        if (avatarCache.has(cacheKey)) {
            return avatarCache.get(cacheKey);
        }

        const canvas = document.createElement("canvas");
        canvas.width = 100;
        canvas.height = 100;
        const ctx = canvas.getContext("2d");

        // Background color based on gender
        const bgColor = gender === "Male" ? "#3B82F6" : gender === "Female" ? "#EC4899" : "#8B5CF6";
        ctx.fillStyle = bgColor;
        ctx.fillRect(0, 0, 100, 100);

        // Get initials
        const names = fullName.trim().split(" ");
        const initials = names.length >= 2
            ? `${names[0][0]}${names[names.length - 1][0]}`.toUpperCase()
            : names[0].substring(0, 2).toUpperCase();

        // Draw text
        ctx.fillStyle = "#FFFFFF";
        ctx.font = "bold 40px Arial";
        ctx.textAlign = "center";
        ctx.textBaseline = "middle";
        ctx.fillText(initials, 50, 50);

        const dataURL = canvas.toDataURL();
        avatarCache.set(cacheKey, dataURL);

        return dataURL;
    }, [avatarCache]);

    // ==============================================================================
    // PAGINATION CONTROLS
    // ==============================================================================

    const goToPage = (page) => {
        if (page >= 1 && page <= totalPages) {
            setCurrentPage(page);
            window.scrollTo({ top: 0, behavior: 'smooth' });
        }
    };

    const PaginationControls = () => (
        <div className="mt-6 flex items-center justify-between border-t pt-4">
            <div className="text-sm text-gray-600">
                Showing {((currentPage - 1) * USERS_PER_PAGE) + 1} to {Math.min(currentPage * USERS_PER_PAGE, totalUsers)} of {totalUsers.toLocaleString()} users
            </div>

            <div className="flex gap-2">
                <button
                    onClick={() => goToPage(1)}
                    disabled={!hasPrevPage || isLoading}
                    className="px-3 py-2 border rounded-lg hover:bg-gray-100 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                >
                    ⟨⟨
                </button>
                <button
                    onClick={() => goToPage(currentPage - 1)}
                    disabled={!hasPrevPage || isLoading}
                    className="px-3 py-2 border rounded-lg hover:bg-gray-100 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                >
                    ⟨ Prev
                </button>

                <div className="px-4 py-2 border rounded-lg bg-blue-50 text-blue-700 font-medium">
                    Page {currentPage} of {totalPages.toLocaleString()}
                </div>

                <button
                    onClick={() => goToPage(currentPage + 1)}
                    disabled={!hasNextPage || isLoading}
                    className="px-3 py-2 border rounded-lg hover:bg-gray-100 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                >
                    Next ⟩
                </button>
                <button
                    onClick={() => goToPage(totalPages)}
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
                {error && (
                    <div className="bg-red-50 border-l-4 border-red-500 text-red-700 p-4 mb-4 rounded-lg animate-slideDown">
                        <p className="font-medium">⚠️ Error</p>
                        <p className="text-sm mt-1">{error}</p>
                    </div>
                )}
                {success && (
                    <div className="bg-green-50 border-l-4 border-green-500 text-green-700 p-4 mb-4 rounded-lg animate-slideDown">
                        <p className="font-medium">✓ Success</p>
                        <p className="text-sm mt-1">{success}</p>
                    </div>
                )}

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
                                {isLoading ? "Saving..." : (editingUser ? "Update User" : "Create User")}
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
                            className="px-6 py-3 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:bg-gray-400 disabled:cursor-not-allowed transition"
                        >
                            {isSearching ? "Searching..." : "Search"}
                        </button>
                        {isSearching && (
                            <div className="absolute right-24 top-1/2 transform -translate-y-1/2">
                                <div className="animate-spin rounded-full h-5 w-5 border-b-2 border-blue-600"></div>
                            </div>
                        )}
                    </div>
                    {searchInfo && (
                        <div className="mt-2 text-sm text-gray-600">
                            Found {searchInfo.count} user{searchInfo.count !== 1 ? 's' : ''}
                            {searchInfo.truncated && " (showing first 200)"}
                        </div>
                    )}
                </div>

                {/* Users Table */}
                <div className="bg-white p-6 rounded-lg shadow-md">
                    <h2 className="text-2xl font-bold mb-4 text-gray-800">
                        Users ({users.length} on this page)
                    </h2>

                    {isLoading && users.length === 0 ? (
                        <div className="text-center py-8">
                            <div className="inline-block animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600"></div>
                            <p className="text-gray-600 mt-2">Loading...</p>
                        </div>
                    ) : users.length > 0 ? (
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
                                    {users.map((user) => (
                                        <tr key={user.id} className="border-b hover:bg-gray-50">
                                            <td className="px-4 py-3">
                                                <img
                                                    src={user.profile_pic
                                                        ? `${API_URL}/${user.profile_pic}`
                                                        : generateInitialsImage(user.full_name, user.gender)}
                                                    alt={user.full_name}
                                                    className="w-12 h-12 rounded-full"
                                                />
                                            </td>
                                            <td className="px-4 py-3 font-medium">{user.full_name}</td>
                                            <td className="px-4 py-3 text-gray-600">@{user.username}</td>
                                            <td className="px-4 py-3">
                                                    <span className={`px-3 py-1 rounded-full text-white text-sm ${
                                                        user.gender === "Male" ? "bg-blue-500" :
                                                            user.gender === "Female" ? "bg-pink-500" : "bg-purple-500"
                                                    }`}>
                                                        {user.gender}
                                                    </span>
                                            </td>
                                            <td className="px-4 py-3">
                                                <div className="flex gap-2">
                                                    <button
                                                        onClick={() => handleEdit(user)}
                                                        className="bg-yellow-500 hover:bg-yellow-600 text-white px-4 py-2 rounded-lg text-sm"
                                                    >
                                                        ✏️ Edit
                                                    </button>
                                                    <button
                                                        onClick={() => handleDelete(user)}
                                                        className="bg-red-600 hover:bg-red-700 text-white px-4 py-2 rounded-lg text-sm"
                                                    >
                                                        🗑️ Delete
                                                    </button>
                                                </div>
                                            </td>
                                        </tr>
                                    ))}
                                    </tbody>
                                </table>
                            </div>

                            {/* Pagination Controls */}
                            {!searchQuery && <PaginationControls />}
                        </>
                    ) : (
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