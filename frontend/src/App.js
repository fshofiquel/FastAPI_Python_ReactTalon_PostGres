import React, { useState, useEffect, useMemo, useCallback } from "react";
import axios from "axios";
import "./App.css";

// ==============================================================================
// CONFIGURATION
// ==============================================================================

// Use environment variable for API URL (configurable per environment)
const API_URL = process.env.REACT_APP_API_URL || "http://localhost:8000";

// File upload constraints (should match backend)
const MAX_FILE_SIZE = 5 * 1024 * 1024; // 5MB
const ALLOWED_FILE_TYPES = ['image/jpeg', 'image/png', 'image/gif', 'image/webp'];

// ==============================================================================
// MAIN COMPONENT
// ==============================================================================

function App() {
    // ==============================================================================
    // STATE MANAGEMENT
    // ==============================================================================
    
    // User data
    const [users, setUsers] = useState([]);
    
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

    // Avatar cache (memoized to prevent recreation on every render)
    const avatarCache = useMemo(() => new Map(), []);

    // ==============================================================================
    // EFFECTS
    // ==============================================================================

    // Fetch all users on mount
    useEffect(() => {
        fetchAllUsers();
    }, []);

    // Debounced search - wait 600ms after user stops typing
    useEffect(() => {
        if (searchQuery.trim() === "") {
            fetchAllUsers();
            return;
        }

        setIsSearching(true);
        const timeoutId = setTimeout(() => {
            performSearch(searchQuery);
        }, 600);

        return () => clearTimeout(timeoutId);
    }, [searchQuery]);

    // Auto-dismiss success messages after 5 seconds
    useEffect(() => {
        if (success) {
            const timer = setTimeout(() => setSuccess(null), 5000);
            return () => clearTimeout(timer);
        }
    }, [success]);

    // ==============================================================================
    // API FUNCTIONS
    // ==============================================================================

    const fetchAllUsers = async () => {
        try {
            setError(null);
            setIsLoading(true);
            
            const res = await axios.get(`${API_URL}/users/`);
            setUsers(res.data);
            setSearchInfo(null);
            
        } catch (err) {
            console.error("Error fetching users:", err);
            const errorMessage = err.response?.data?.detail || err.message || "Failed to fetch users";
            setError(errorMessage);
            setUsers([]);
        } finally {
            setIsSearching(false);
            setIsLoading(false);
        }
    };

    const performSearch = async (query) => {
        try {
            setError(null);
            
            const res = await axios.get(`${API_URL}/ai/search`, {
                params: { query }
            });
            
            setUsers(res.data.results);
            setSearchInfo({
                count: res.data.count,
                message: res.data.message
            });
            
        } catch (err) {
            console.error("Error searching users:", err);
            const errorMessage = err.response?.data?.detail || err.message || "Search failed";
            setError(`Search failed: ${errorMessage}`);
            setUsers([]);
            setSearchInfo(null);
        } finally {
            setIsSearching(false);
        }
    };

    // ==============================================================================
    // FORM HANDLERS
    // ==============================================================================

    const handleInputChange = (e) => {
        const { name, value } = e.target;
        setFormData({ ...formData, [name]: value });
    };

    const validateFile = (file) => {
        // Check file size
        if (file.size > MAX_FILE_SIZE) {
            const sizeMB = (file.size / (1024 * 1024)).toFixed(1);
            const maxSizeMB = (MAX_FILE_SIZE / (1024 * 1024)).toFixed(1);
            throw new Error(`File too large (${sizeMB}MB). Maximum size is ${maxSizeMB}MB.`);
        }

        // Check file type
        if (!ALLOWED_FILE_TYPES.includes(file.type)) {
            throw new Error(`Invalid file type. Allowed: ${ALLOWED_FILE_TYPES.join(', ')}`);
        }
    };

    const handleFileChange = (e) => {
        const file = e.target.files[0];
        
        if (!file) {
            setFormData({ ...formData, profile_pic: null });
            setPreviewImage(null);
            return;
        }

        try {
            // Validate file
            validateFile(file);
            
            setFormData({ ...formData, profile_pic: file });

            // Generate preview
            const reader = new FileReader();
            reader.onloadend = () => setPreviewImage(reader.result);
            reader.readAsDataURL(file);
            
            setError(null); // Clear any previous errors
            
        } catch (err) {
            setError(err.message);
            setFormData({ ...formData, profile_pic: null });
            setPreviewImage(null);
            e.target.value = null; // Reset file input
        }
    };

    const validateForm = () => {
        // Validate full name
        if (!formData.full_name || formData.full_name.trim().length < 2) {
            throw new Error("Full name must be at least 2 characters");
        }
        if (formData.full_name.length > 255) {
            throw new Error("Full name must be less than 255 characters");
        }

        // Validate username
        if (!formData.username || formData.username.trim().length < 3) {
            throw new Error("Username must be at least 3 characters");
        }
        if (formData.username.length > 50) {
            throw new Error("Username must be less than 50 characters");
        }
        if (!/^[a-zA-Z0-9_]+$/.test(formData.username)) {
            throw new Error("Username can only contain letters, numbers, and underscores");
        }

        // Validate password (only for new users)
        if (!editingUser) {
            if (!formData.password || formData.password.length < 8) {
                throw new Error("Password must be at least 8 characters");
            }
        } else if (formData.password && formData.password.length < 8) {
            throw new Error("Password must be at least 8 characters (leave empty to keep current password)");
        }

        // Validate gender
        if (!formData.gender) {
            throw new Error("Please select a gender");
        }
        if (!["Male", "Female", "Other"].includes(formData.gender)) {
            throw new Error("Invalid gender selection");
        }
    };

    const handleSubmit = async (e) => {
        e.preventDefault();
        
        try {
            setError(null);
            setIsLoading(true);

            // Validate form
            validateForm();

            const data = new FormData();
            data.append("full_name", formData.full_name.trim());
            data.append("username", formData.username.trim());
            data.append("password", formData.password);
            data.append("gender", formData.gender);
            
            if (formData.profile_pic) {
                data.append("profile_pic", formData.profile_pic);
            }

            if (editingUser) {
                await axios.put(`${API_URL}/users/${editingUser.id}`, data, {
                    headers: { "Content-Type": "multipart/form-data" },
                });
                setSuccess(`User "${formData.username}" updated successfully!`);
            } else {
                await axios.post(`${API_URL}/users/`, data, {
                    headers: { "Content-Type": "multipart/form-data" },
                });
                setSuccess(`User "${formData.username}" created successfully!`);
            }

            // Refresh list based on current search state
            if (searchQuery.trim()) {
                await performSearch(searchQuery);
            } else {
                await fetchAllUsers();
            }
            
            resetForm();
            setShowForm(false);
            
        } catch (err) {
            console.error("Error saving user:", err);
            const errorMessage = err.response?.data?.detail || err.message || "Failed to save user";
            setError(errorMessage);
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

    const handleDelete = async (user) => {
        if (!window.confirm(`Are you sure you want to delete user "${user.username}"?`)) {
            return;
        }
        
        try {
            setError(null);
            setIsLoading(true);
            
            await axios.delete(`${API_URL}/users/${user.id}`);
            
            setSuccess(`User "${user.username}" deleted successfully!`);

            // Refresh based on current view
            if (searchQuery.trim()) {
                await performSearch(searchQuery);
            } else {
                await fetchAllUsers();
            }
            
        } catch (err) {
            console.error("Error deleting user:", err);
            const errorMessage = err.response?.data?.detail || err.message || "Failed to delete user";
            setError(errorMessage);
        } finally {
            setIsLoading(false);
        }
    };

    const resetForm = () => {
        setFormData({
            full_name: "",
            username: "",
            password: "",
            gender: "",
            profile_pic: null,
        });
        setPreviewImage(null);
        setEditingUser(null);
        setError(null);
    };

    const cancelForm = () => {
        resetForm();
        setShowForm(false);
    };

    // ==============================================================================
    // AVATAR GENERATION (Memoized for Performance)
    // ==============================================================================

    const generateInitialsImage = useCallback((fullName, gender) => {
        // Check cache first
        const cacheKey = `${fullName}-${gender}`;
        if (avatarCache.has(cacheKey)) {
            return avatarCache.get(cacheKey);
        }

        // Generate avatar
        const initials = fullName
            .split(" ")
            .map((n) => n[0]?.toUpperCase() || "")
            .join("")
            .slice(0, 2);

        const bgColors = {
            "Male": "#3B82F6",
            "Female": "#EC4899",
            "Other": "#8B5CF6",
        };
        const bgColor = bgColors[gender] || "#9CA3AF";

        const canvas = document.createElement("canvas");
        canvas.width = 80;
        canvas.height = 80;
        const ctx = canvas.getContext("2d");

        // Draw background
        ctx.fillStyle = bgColor;
        ctx.fillRect(0, 0, 80, 80);

        // Draw initials
        ctx.fillStyle = "#FFFFFF";
        ctx.font = "bold 32px Arial, sans-serif";
        ctx.textAlign = "center";
        ctx.textBaseline = "middle";
        ctx.fillText(initials, 40, 40);

        const dataUrl = canvas.toDataURL("image/png");
        
        // Cache the result
        avatarCache.set(cacheKey, dataUrl);
        
        return dataUrl;
    }, [avatarCache]);

    // ==============================================================================
    // RENDER
    // ==============================================================================

    return (
        <div className="min-h-screen bg-gray-100 p-8">
            <div className="max-w-7xl mx-auto">
                
                {/* Header */}
                <div className="mb-8">
                    <h1 className="text-4xl font-bold text-gray-800 mb-2">
                        User Management System
                    </h1>
                    <p className="text-gray-600">
                        AI-powered user management with natural language search
                    </p>
                </div>

                {/* Error Banner */}
                {error && (
                    <div className="bg-red-100 border border-red-400 text-red-700 px-4 py-3 rounded-lg mb-4 animate-fadeIn flex justify-between items-center">
                        <div className="flex items-center">
                            <span className="text-xl mr-2">⚠️</span>
                            <span>{error}</span>
                        </div>
                        <button
                            onClick={() => setError(null)}
                            className="text-red-700 hover:text-red-900 font-bold text-xl"
                        >
                            ✕
                        </button>
                    </div>
                )}

                {/* Success Banner */}
                {success && (
                    <div className="bg-green-100 border border-green-400 text-green-700 px-4 py-3 rounded-lg mb-4 animate-fadeIn flex justify-between items-center">
                        <div className="flex items-center">
                            <span className="text-xl mr-2">✅</span>
                            <span>{success}</span>
                        </div>
                        <button
                            onClick={() => setSuccess(null)}
                            className="text-green-700 hover:text-green-900 font-bold text-xl"
                        >
                            ✕
                        </button>
                    </div>
                )}

                {/* Add User Button */}
                {!showForm && (
                    <button
                        onClick={() => setShowForm(true)}
                        disabled={isLoading}
                        className="mb-6 bg-blue-600 hover:bg-blue-700 text-white font-semibold py-3 px-6 rounded-lg shadow-md transition-all disabled:opacity-50 disabled:cursor-not-allowed"
                    >
                        ➕ Add New User
                    </button>
                )}

                {/* User Form */}
                {showForm && (
                    <form
                        onSubmit={handleSubmit}
                        className="bg-white p-6 rounded-lg shadow-md mb-6 animate-fadeIn"
                    >
                        <h2 className="text-2xl font-bold mb-4 text-gray-800">
                            {editingUser ? "Edit User" : "Create New User"}
                        </h2>

                        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                            {/* Full Name */}
                            <div>
                                <label className="block text-sm font-medium text-gray-700 mb-1">
                                    Full Name *
                                </label>
                                <input
                                    type="text"
                                    name="full_name"
                                    value={formData.full_name}
                                    onChange={handleInputChange}
                                    placeholder="John Doe"
                                    required
                                    minLength={2}
                                    maxLength={255}
                                    disabled={isLoading}
                                    className="w-full px-4 py-2 border rounded-lg focus:ring-2 focus:ring-blue-500 disabled:bg-gray-100"
                                />
                            </div>

                            {/* Username */}
                            <div>
                                <label className="block text-sm font-medium text-gray-700 mb-1">
                                    Username *
                                </label>
                                <input
                                    type="text"
                                    name="username"
                                    value={formData.username}
                                    onChange={handleInputChange}
                                    placeholder="johndoe"
                                    required
                                    minLength={3}
                                    maxLength={50}
                                    pattern="[a-zA-Z0-9_]+"
                                    disabled={isLoading}
                                    className="w-full px-4 py-2 border rounded-lg focus:ring-2 focus:ring-blue-500 disabled:bg-gray-100"
                                />
                                <p className="text-xs text-gray-500 mt-1">
                                    Letters, numbers, and underscores only
                                </p>
                            </div>

                            {/* Password */}
                            <div>
                                <label className="block text-sm font-medium text-gray-700 mb-1">
                                    Password {editingUser ? "(leave empty to keep current)" : "*"}
                                </label>
                                <input
                                    type="password"
                                    name="password"
                                    value={formData.password}
                                    onChange={handleInputChange}
                                    placeholder={editingUser ? "Leave blank to keep password" : "Minimum 8 characters"}
                                    required={!editingUser}
                                    minLength={8}
                                    disabled={isLoading}
                                    className="w-full px-4 py-2 border rounded-lg focus:ring-2 focus:ring-blue-500 disabled:bg-gray-100"
                                />
                            </div>

                            {/* Gender */}
                            <div>
                                <label className="block text-sm font-medium text-gray-700 mb-1">
                                    Gender *
                                </label>
                                <select
                                    name="gender"
                                    value={formData.gender}
                                    onChange={handleInputChange}
                                    required
                                    disabled={isLoading}
                                    className="w-full px-4 py-2 border rounded-lg focus:ring-2 focus:ring-blue-500 disabled:bg-gray-100"
                                >
                                    <option value="">Select Gender</option>
                                    <option value="Male">Male</option>
                                    <option value="Female">Female</option>
                                    <option value="Other">Other</option>
                                </select>
                            </div>
                        </div>

                        {/* Profile Picture */}
                        <div className="mt-4">
                            <label className="block text-sm font-medium text-gray-700 mb-1">
                                Profile Picture (Optional)
                            </label>
                            <input
                                type="file"
                                accept="image/jpeg,image/png,image/gif,image/webp"
                                onChange={handleFileChange}
                                disabled={isLoading}
                                className="w-full disabled:bg-gray-100"
                            />
                            <p className="text-xs text-gray-500 mt-1">
                                Max 5MB. Formats: JPEG, PNG, GIF, WebP
                            </p>
                            {previewImage && (
                                <img
                                    src={previewImage}
                                    alt="Preview"
                                    className="w-20 h-20 mt-2 object-cover rounded-full border-2 border-gray-300"
                                />
                            )}
                        </div>

                        {/* Form Actions */}
                        <div className="mt-6 flex gap-4">
                            <button
                                type="submit"
                                disabled={isLoading}
                                className="bg-green-600 hover:bg-green-700 text-white font-semibold py-2 px-6 rounded-lg disabled:opacity-50 disabled:cursor-not-allowed transition-all"
                            >
                                {isLoading ? "Saving..." : (editingUser ? "Update User" : "Create User")}
                            </button>
                            <button
                                type="button"
                                onClick={cancelForm}
                                disabled={isLoading}
                                className="bg-gray-500 hover:bg-gray-600 text-white font-semibold py-2 px-6 rounded-lg disabled:opacity-50 disabled:cursor-not-allowed transition-all"
                            >
                                Cancel
                            </button>
                        </div>
                    </form>
                )}

                {/* AI Search Bar */}
                <div className="bg-white p-4 rounded-lg shadow-md mb-6 animate-fadeIn">
                    <div className="relative">
                        <input
                            type="text"
                            value={searchQuery}
                            onChange={(e) => setSearchQuery(e.target.value)}
                            placeholder='🔍 Smart search... Try "female users" or "users named Taylor" or "list all male"'
                            disabled={isLoading}
                            className="w-full px-4 py-3 pr-12 border rounded-lg focus:ring-2 focus:ring-blue-500 text-gray-700 disabled:bg-gray-100"
                        />
                        {isSearching && (
                            <div className="absolute right-4 top-1/2 transform -translate-y-1/2">
                                <div className="animate-spin rounded-full h-5 w-5 border-b-2 border-blue-600"></div>
                            </div>
                        )}
                        {searchQuery && !isSearching && (
                            <button
                                onClick={() => setSearchQuery("")}
                                className="absolute right-4 top-1/2 transform -translate-y-1/2 text-gray-400 hover:text-gray-600 text-xl"
                            >
                                ✕
                            </button>
                        )}
                    </div>

                    {/* Search Info */}
                    {searchInfo && (
                        <div className="mt-2 text-sm text-gray-600">
                            {searchInfo.message || `Found ${searchInfo.count} user${searchInfo.count !== 1 ? 's' : ''}`}
                        </div>
                    )}
                    {searchQuery && users.length === 0 && !isSearching && !isLoading && (
                        <div className="mt-2 text-sm text-gray-500">
                            No users found matching "{searchQuery}"
                        </div>
                    )}
                </div>

                {/* Users Table */}
                <div className="bg-white p-6 rounded-lg shadow-md animate-fadeIn">
                    <h2 className="text-2xl font-bold mb-4 text-gray-800">
                        Users ({users.length})
                    </h2>
                    
                    {isLoading && users.length === 0 ? (
                        <div className="text-center py-8">
                            <div className="inline-block animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600"></div>
                            <p className="text-gray-600 mt-2">Loading...</p>
                        </div>
                    ) : users.length > 0 ? (
                        <div className="overflow-x-auto">
                            <table className="min-w-full text-left">
                                <thead className="border-b bg-gray-50">
                                    <tr>
                                        <th className="px-4 py-3 text-sm font-semibold text-gray-700">Avatar</th>
                                        <th className="px-4 py-3 text-sm font-semibold text-gray-700">Full Name</th>
                                        <th className="px-4 py-3 text-sm font-semibold text-gray-700">Username</th>
                                        <th className="px-4 py-3 text-sm font-semibold text-gray-700">Gender</th>
                                        <th className="px-4 py-3 text-sm font-semibold text-gray-700">Actions</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {users.map((user) => (
                                        <tr key={user.id} className="border-b hover:bg-gray-50 transition-colors">
                                            <td className="px-4 py-3">
                                                {user.profile_pic ? (
                                                    <img
                                                        src={`${API_URL}/${user.profile_pic}`}
                                                        alt={user.full_name}
                                                        className="w-16 h-16 rounded-full object-cover border-2 border-gray-300"
                                                    />
                                                ) : (
                                                    <img
                                                        src={generateInitialsImage(user.full_name, user.gender)}
                                                        alt={user.full_name}
                                                        className="w-16 h-16 rounded-full border-2 border-gray-300"
                                                    />
                                                )}
                                            </td>
                                            <td className="px-4 py-3 font-medium text-gray-900">{user.full_name}</td>
                                            <td className="px-4 py-3 text-gray-600">@{user.username}</td>
                                            <td className="px-4 py-3">
                                                <span
                                                    className={`px-3 py-1 rounded-full text-white text-sm font-medium ${
                                                        user.gender === "Male"
                                                            ? "bg-blue-500"
                                                            : user.gender === "Female"
                                                            ? "bg-pink-500"
                                                            : "bg-purple-500"
                                                    }`}
                                                >
                                                    {user.gender}
                                                </span>
                                            </td>
                                            <td className="px-4 py-3">
                                                <div className="flex gap-2">
                                                    <button
                                                        onClick={() => handleEdit(user)}
                                                        disabled={isLoading}
                                                        className="bg-yellow-500 hover:bg-yellow-600 text-white px-4 py-2 rounded-lg text-sm font-medium transition-all disabled:opacity-50 disabled:cursor-not-allowed"
                                                    >
                                                        ✏️ Edit
                                                    </button>
                                                    <button
                                                        onClick={() => handleDelete(user)}
                                                        disabled={isLoading}
                                                        className="bg-red-600 hover:bg-red-700 text-white px-4 py-2 rounded-lg text-sm font-medium transition-all disabled:opacity-50 disabled:cursor-not-allowed"
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
                    ) : (
                        <div className="text-center py-8 text-gray-500">
                            <p className="text-lg">No users found</p>
                            <p className="text-sm mt-2">Click "Add New User" to create your first user</p>
                        </div>
                    )}
                </div>
            </div>
        </div>
    );
}

export default App;
